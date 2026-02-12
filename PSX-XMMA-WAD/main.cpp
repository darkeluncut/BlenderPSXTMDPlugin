#include <windows.h>
#include <filesystem>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <stdio.h>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <sys/stat.h> // For directory creation
#include <dirent.h>   // For directory traversal
#include <algorithm>  // For sorting filenames

#ifdef WINDOWS
    #include <direct.h>
    #define GetCurrentDir _getcwd
#else
    #include <unistd.h>
    #define GetCurrentDir getcwd
 #endif

#ifdef _WIN32
#include <direct.h>   // For _mkdir
#define mkdir _mkdir
#endif


using namespace std;

int WADunpack(std::string Str); //declare
uint8_t WADmode = 1;

#pragma pack(push, 1)
struct Header {
    char idstring[4]; // "PWF "
    uint8_t dummy;
    uint8_t some_size[3];
    uint32_t ver;
    uint32_t files;
};
#pragma pack(pop)

uint32_t read3Bytes(std::ifstream &file) {
    uint8_t bytes[3];
    file.read(reinterpret_cast<char*>(bytes), 3);
    return (bytes[0] << 16) | (bytes[1] << 8) | bytes[2];
}

std::string readString(std::ifstream &file) {
    std::string result;
    char ch;
    while (file.get(ch)) {
        if (ch == '\0') break;
        result += ch;
    }
    return result;
}

void createDirectory(const std::string &path) {
#ifdef _WIN32
        _mkdir(path.c_str());
    #else
        mkdir(path.c_str(), 0755);
    #endif
}

void extractFiles(std::ifstream &file, uint32_t files, uint8_t mode, const std::string &outputDir) {
    for (uint32_t i = 0; i < files; ++i) {
        if (mode == 1) {
            uint32_t offset, size, flags;
            uint32_t dummy1, dummy2;

            file.read(reinterpret_cast<char*>(&offset), 3);
            file.read(reinterpret_cast<char*>(&dummy1), 2); // Read 2 bits as dummy
            file.read(reinterpret_cast<char*>(&size), 3);
            file.read(reinterpret_cast<char*>(&dummy2), 12); // Read 12 bits as dummy
            file.read(reinterpret_cast<char*>(&flags), 1);

            offset = (offset >> 8) * 0x800;
            size = (size >> 12) * 4;

            if (flags & 0x80) {
                std::streampos tmp = file.tellg();
                file.seekg(offset, std::ios::beg);

                char id[5] = {0};
                file.read(id, 4);
                if (std::string(id) == "EWDF") {
                    uint32_t xsize, header_size, some_crc;
                    file.read(reinterpret_cast<char*>(&xsize), sizeof(xsize));
                    file.read(reinterpret_cast<char*>(&header_size), sizeof(header_size));
                    file.read(reinterpret_cast<char*>(&some_crc), sizeof(some_crc));
                    std::string name = readString(file);

                    std::ostringstream formatted_name;
                    formatted_name << std::hex << std::setw(8) << std::setfill('0') << some_crc << "_" << name;

                    offset += header_size;
                    size -= header_size;

                    // Extract the file content
                    std::vector<char> data(size);
                    file.read(data.data(), size);
                    std::ofstream outfile(outputDir + "/" + formatted_name.str(), std::ios::binary);
                    outfile.write(data.data(), size);
                }
                file.seekg(tmp);
            }
        } else {
            uint32_t offset, size;
            file.read(reinterpret_cast<char*>(&offset), sizeof(offset));
            file.read(reinterpret_cast<char*>(&size), sizeof(size));

            // Read the file content and save it
            std::vector<char> data(size);
            std::streampos current_pos = file.tellg();
            file.seekg(offset, std::ios::beg);
            file.read(data.data(), size);
            file.seekg(current_pos, std::ios::beg);  // Return to the original position

            std::ostringstream filename;
            filename << "file_" << std::setw(5) << std::setfill('0') << i;

            std::ofstream outfile(outputDir + "/" + filename.str(), std::ios::binary);
            outfile.write(data.data(), size);
        }
    }
}

//-----------------------------------------------------------------------------------------
std::vector<std::string> getFiles(const std::string& directory) {
    std::vector<std::string> files;
    DIR* dir = opendir(directory.c_str());
    struct dirent* entry;
    while ((entry = readdir(dir)) != nullptr) {
        std::string filepath = directory + "/" + entry->d_name;
        struct stat path_stat;
        stat(filepath.c_str(), &path_stat);
        if (S_ISREG(path_stat.st_mode)) { // If the entry is a regular file
            files.emplace_back(entry->d_name);
        }
    }
    closedir(dir);
    std::sort(files.begin(), files.end());
    return files;
}

void write3Bytes(std::ofstream &file, uint32_t value) {
    uint8_t bytes[3] = {
        static_cast<uint8_t>((value >> 16) & 0xFF),
        static_cast<uint8_t>((value >> 8) & 0xFF),
        static_cast<uint8_t>(value & 0xFF)
    };
    file.write(reinterpret_cast<char*>(bytes), 3);
}

void alignToBoundary(std::ofstream &file, uint32_t boundary) {
    std::streampos currentPos = file.tellp();
    uint32_t paddingSize = boundary - (currentPos % boundary);
    if (paddingSize != boundary) {
        for (uint32_t i = 0; i < paddingSize; ++i) {
            file.put(0);
        }
    }
}

void createBinary(const std::string& outputFileName, const std::string& headerFileName, const std::string& dataDir) {
    std::ifstream headerFile(headerFileName, std::ios::binary);
    if (!headerFile) {
        std::cerr << "Cannot open header file!" << std::endl;
        return;
    }

    std::vector<char> headerData(0x800);
    headerFile.read(headerData.data(), 0x800);
    headerFile.close();

    std::vector<std::string> files = getFiles(dataDir);

    std::ofstream outFile(outputFileName, std::ios::binary);
    if (!outFile) {
        std::cerr << "Cannot open output file!" << std::endl;
        return;
    }

    outFile.write(headerData.data(), 0x800);

    // Write placeholder for file offsets and sizes
    uint32_t offsetBlockStart = 0x800;
    uint32_t offsetBlockSize = files.size() * (sizeof(uint32_t) * 2);
    std::vector<uint32_t> offsets(files.size());
    std::vector<uint32_t> sizes(files.size());

    // Calculate padding to ensure first file starts at 0x2000
    uint32_t paddingSize = 0;//x610;

    // Move to the end of the placeholder block to start writing file data
    outFile.seekp(offsetBlockStart + offsetBlockSize + paddingSize, std::ios::beg);

    for (size_t i = 0; i < files.size(); ++i) {
        const std::string& fileName = files[i];

        std::ifstream file(dataDir + "/" + fileName, std::ios::binary);
        if (!file) {
            std::cerr << "Cannot open data file: " << fileName << std::endl;
            continue;
        }

        std::vector<char> fileData((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        file.close();

        // Align to the next 0x800-byte boundary
        alignToBoundary(outFile, 0x800);

        // Write file data
        uint32_t offset = static_cast<uint32_t>(outFile.tellp());
        uint32_t size = static_cast<uint32_t>(fileData.size());

        outFile.write(fileData.data(), size);

        offsets[i] = offset;
        sizes[i] = size;
    }

    // Go back to write offsets and sizes
    outFile.seekp(offsetBlockStart, std::ios::beg);
    for (size_t i = 0; i < files.size(); ++i) {
        outFile.write(reinterpret_cast<const char*>(&offsets[i]), sizeof(offsets[i]));
        outFile.write(reinterpret_cast<const char*>(&sizes[i]), sizeof(sizes[i]));
    }

    // Calculate total size of the binary and pad with zeros to align to 0x800 bytes
    outFile.seekp(0, std::ios::end);
    std::streampos fileSize = outFile.tellp();
    uint32_t npaddingSize = 0x800 - (fileSize % 0x800);
    for (uint32_t i = 0; i < npaddingSize; ++i) {
        outFile.put(0);
    }

    //Append proper size to header
    uint32_t totlSize = fileSize + npaddingSize;
    outFile.seekp(0x04, std::ios::beg);
    outFile.write(reinterpret_cast<const char*>(&totlSize), sizeof(totlSize));

    //Append proper file count to header
    uint32_t hedFSize = files.size();
    outFile.seekp(0x0c, std::ios::beg);
    outFile.write(reinterpret_cast<const char*>(&hedFSize), sizeof(hedFSize));

    outFile.close();
}


int WADpack()
{
    const std::string headerFileName = "wadhead.hed";
    const std::string dataDir = "WADdata";
    const std::string outputFileName = "WADnew.WAD";

    createBinary(outputFileName, headerFileName, dataDir);

    return 0;
}


int main( int argc,      // Number of strings in array argv
          char *argv[])   // Array of command-line argument strings
{
    //Print debug data
    cout << "XMEN Mutant Academy WAD Extractor/Packer" << endl;
    cout << "Input either wad.wad to extract" << endl;
    cout << "Or wadhead.hed to pack back" << endl;
    cout << "Example: app.exe wad.wad " << endl;

    if (argc <= 1)
    {
        return 0;
    }

    std::string input(argv[1]); //Got the filename argument
    std::string base_filename = input.substr(input.find_last_of("/\\") + 1);

    std::string::size_type const p(base_filename.find_last_of('.'));
    std::string fileNoExt = base_filename.substr(0, p);
    std::string fileExt = base_filename.substr(base_filename.find_last_of('.') + 1);


    //Unpacking or Repacking
    if (fileExt == "wad" || fileExt == "WAD")
    {
	    cout << "Found wad. Unpacking" << endl;
        WADunpack(input);
    }
    else if (fileExt == "hed" || fileExt == "HED")
    {
	    cout << "Found header. Packing" << endl;
        WADpack();
    }
    else
    {
	    cout << "Didn't find anything. Exiting" << endl;

    }

   return 0;
}

int WADunpack(std::string Str)
{
   const std::string outputDir = "WADdata";
   createDirectory(outputDir);

   char cCurrentPath[FILENAME_MAX];
   GetCurrentDir(cCurrentPath, sizeof(cCurrentPath));
   std::string cCurrentPathStr = cCurrentPath;

   char fullFilename[FILENAME_MAX];
   GetFullPathName(Str.c_str(), FILENAME_MAX, fullFilename, nullptr);

   std::string filename = fullFilename;
   cout << filename << endl;


   // Open the input file in binary mode
    std::ifstream inputFile(filename, std::ios::binary);
    if (!inputFile) {
        std::cerr << "Error: Could not open file " << filename << std::endl;
        return 0;
    }
    else
    {
        cout << "Opened WAD" << endl;
    }

    //Write header

    std::streampos offset = 0x0;
    std::streamsize size =  0x800;

    // Seek to the specified offset in the input file
    inputFile.seekg(offset);

    // Read the specified number of bytes from the input file
    std::vector<char> buffer(size);
    inputFile.read(buffer.data(), size);

    // Create an output file for the current chunk
    std::string outputFilename;
    outputFilename.append(cCurrentPath);
    outputFilename.append("/wadhead.hed");
    std::ofstream outputFile(outputFilename, std::ios::binary);

    // Write the buffer to the output file
    outputFile.write(buffer.data(), size);
    //---------------------------------------------------------

    Header header;
    inputFile.seekg(std::ios::beg);
    inputFile.read(reinterpret_cast<char*>(&header), sizeof(header));
    if (std::string(header.idstring, 4) != "PWF ") {
        std::cerr << "Invalid file format!" << std::endl;
        return 1;
    }
    else
    {
        cout << "Proper Header" << endl;
    }

    uint32_t some_size = read3Bytes(inputFile);
    uint32_t ver = header.ver;
    uint32_t files = header.files;

    inputFile.seekg(0x800, std::ios::beg);
    uint32_t test1, test2;
    inputFile.read(reinterpret_cast<char*>(&test1), sizeof(test1));
    inputFile.read(reinterpret_cast<char*>(&test2), sizeof(test2));
    inputFile.seekg(-8, std::ios::cur);
    if ((test1 >> 24) == 0 && (test2 >> 24) == 0) {
        WADmode = 2;
    }

    cout << "Extracting Files Cnt: " << files << endl;
    cout << "WADmode: " << WADmode << endl;
    extractFiles(inputFile, files, WADmode, outputDir);


    // Close the input file
    inputFile.close();

   return 1;
}
