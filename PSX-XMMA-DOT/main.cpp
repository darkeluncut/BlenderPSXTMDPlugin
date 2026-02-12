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
#include <unordered_map>

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


int DOTunpack(std::string Str); //declare
void DOTpack();

std::string base_filename;
std::string fileNoExt;
std::string fileExt;

#pragma pack(push, 1)
struct Header {
    uint32_t header; //Something here
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

void extractFiles(std::ifstream &file, const std::string &outputDir) {
    uint32_t lastf_end;
    uint32_t fileofno;

    uint32_t header;
    file.seekg(0x0, std::ios::beg);
    file.read(reinterpret_cast<char*>(&header), sizeof(header));

    file.seekg(0x4, std::ios::beg);

    std::vector<uint32_t> offsets;
    uint32_t offset;
    std::vector<std::pair<uint32_t, size_t>> originalOrder;// Pair of offset and original index
    size_t index = 0;

    // Read offsets into the vector and store original order
    while (true) {
        file.read(reinterpret_cast<char*>(&offset), sizeof(offset));
        if (!file || offset == 0) {
            break;
        }
        offsets.push_back(offset);
        originalOrder.push_back(std::make_pair(offset, index));
        ++index;
    }
    for (size_t i = 0; i < originalOrder.size(); ++i)
    {
        std::cout << "Order. " << originalOrder[i].second << " , " << originalOrder[i].first << std::endl;
    }


    // Sort offsets
    std::sort(offsets.begin(), offsets.end());

    // Compute sizes
    std::vector<uint32_t> sizes;
    for (size_t i = 0; i < offsets.size() - 1; ++i) {
        sizes.push_back(offsets[i + 1] - offsets[i]);
    }

    // Get file size to determine the last size
    file.seekg(0, std::ios::end);
    uint32_t fileSize = file.tellg();
    if (!offsets.empty()) {
        sizes.push_back(fileSize - offsets.back());
    }

    // Create table.txt to store original order of filenames
    std::string TfileName = fileNoExt + (".dhed");
    std::ofstream tableFile(TfileName);
    if (!tableFile) {
        std::cerr << "Unable to create table file." << std::endl;
        return;
    }

    // Write the header to the table file
    tableFile << "Header: " << std::hex << header << std::endl;

    // Read data segments and write to separate files with original index in filenames
    for (size_t i = 0; i < offsets.size(); ++i) {
        size_t originalIndex = 0;
        for (size_t j = 0; j < originalOrder.size(); ++j) {
            if (originalOrder[j].first == offsets[i]) {
                originalIndex = originalOrder[j].second;
                break;
            }
        }

        file.seekg(offsets[i], std::ios::beg);
        std::vector<char> data(sizes[i]);
        file.read(data.data(), sizes[i]);

        if (!file) {
            std::cerr << "Error reading data from file." << std::endl;
            return;
        }

        std::ostringstream filename;
        filename << "file_" << std::setw(5) << std::setfill('0') << i; // Use original index
        tableFile << filename.str() << " " << originalIndex << std::endl;

        std::ofstream outfile(outputDir + "/" + filename.str(), std::ios::binary);
        if (!outfile) {
            std::cerr << "Unable to open output file." << std::endl;
            return;
        }
        outfile.write(data.data(), sizes[i]);
    }


    tableFile.close();




}

//-----------------------------------------------------------------------------------------
void listFiles(const std::string& dirPath, std::vector<std::string>& files) {
    WIN32_FIND_DATAA findFileData;
    HANDLE hFind = FindFirstFileA((dirPath + "\\*").c_str(), &findFileData);
    if (hFind == INVALID_HANDLE_VALUE) {
        std::cerr << "Error opening directory: " << dirPath << std::endl;
        return;
    }

    do {
        if (!(findFileData.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
            files.push_back(dirPath + "\\" + findFileData.cFileName);
        }
    } while (FindNextFileA(hFind, &findFileData) != 0);

    FindClose(hFind);
}

void bubbleSortDescending(std::vector<uint32_t>& vec) {
    bool swapped;
    size_t n = vec.size();
    do {
        swapped = false;
        for (size_t i = 1; i < n; ++i) {
            if (vec[i - 1] < vec[i]) { // Change to descending order
                std::swap(vec[i - 1], vec[i]);
                swapped = true;
            }
        }
        --n;
    } while (swapped);
}

void DOTpack() {
    // Output file
    std::ofstream outfile("Dot1_new.dot", std::ios::binary);
    if (!outfile) {
        std::cerr << "Unable to create Dot1_new.dot file." << std::endl;
        return;
    }

    // Write header 0x01030000 at the beginning of the file
    //uint32_t header = 0x00000301;
    //outfile.write(reinterpret_cast<const char*>(&header), sizeof(header));


    // Directory containing dot data files
    char cCurrentPath[FILENAME_MAX];
    GetCurrentDir(cCurrentPath, sizeof(cCurrentPath));
    std::string cCurrentPathStr = cCurrentPath;
    std::string dotDataDir = cCurrentPathStr + "\\DOTdata"; // Adjust your directory path

    // Collect files in DOTdata directory
    std::vector<std::string> files;
    listFiles(dotDataDir, files);

    // Sort files alphabetically
    std::sort(files.begin(), files.end());

    // Calculate offsets
    std::vector<uint32_t> offsets(files.size());
    std::vector<uint32_t> sizes(files.size());

    uint32_t totalSize = 0;
    for (size_t i = 0; i < files.size(); ++i) {
        std::ifstream infile(files[i], std::ios::binary | std::ios::ate);
        if (!infile) {
            std::cerr << "Error opening file: " << files[i] << std::endl;
            return;
        }
        sizes[i] = infile.tellg();
        offsets[i] = totalSize;
        totalSize += sizes[i];
    }
    // Calculate size of offset table (offsets + header + termination)
    size_t offsetTableSize = (files.size() + 2) * sizeof(uint32_t);

    // Read table.txt to get filenames and NewIndex values
    std::string TfileName = fileNoExt + (".dhed");
    std::ifstream tableFile(TfileName);
    if (!tableFile) {
        std::cerr << "Error opening table." << std::endl;
        return;
    }
    // Read the header from tableFile
    std::string headerLine;
    std::getline(tableFile, headerLine);
    uint32_t header = std::stoul(headerLine.substr(8), nullptr, 16);

    // Create a map to store filename to NewIndex mapping
    std::unordered_map<std::string, int> fileNewIndexMap;
    std::string filename, newIndexStr;
    int newIndex;
    while (tableFile >> filename >> newIndexStr) {
        newIndex = std::stoi(newIndexStr, nullptr, 16);  // Convert hex string to int
        fileNewIndexMap[filename] = newIndex;
    }
    tableFile.close();

    // Write the header at the beginning of the file
    outfile.write(reinterpret_cast<const char*>(&header), sizeof(header));

    // Compute absolute offsets (including header size)
    std::vector<uint32_t> absoluteOffsets(files.size());
    for (size_t i = 0; i < files.size(); ++i) {
        const std::string& filename = files[i];
        int newIndex = fileNewIndexMap[filename.substr(filename.find_last_of("\\/") + 1)]; // Extract filename from path
        absoluteOffsets[newIndex] = offsets[i] + offsetTableSize;
    }

    // Write offset table starting from 0x04
    outfile.seekp(0x04, std::ios::beg);
    for (size_t i = 0; i < files.size(); ++i) {
        outfile.write(reinterpret_cast<const char*>(&absoluteOffsets[i]), sizeof(uint32_t));
    }

    // Terminate offset table with 0x00000000
    uint32_t termination = 0x00000000;
    outfile.write(reinterpret_cast<const char*>(&termination), sizeof(uint32_t));


    // Write files to appropriate offsets
    for (size_t i = 0; i < files.size(); ++i) {
        std::ifstream infile(files[i], std::ios::binary);
        if (!infile) {
            std::cerr << "Error opening file: " << files[i] << std::endl;
            return;
        }
        infile.seekg(0, std::ios::beg);

        // Seek to absolute offset for writing
        outfile.seekp(offsets[i] + offsetTableSize, std::ios::beg);

        // Read and write file content
        std::vector<char> buffer(sizes[i]);
        infile.read(buffer.data(), sizes[i]);
        outfile.write(buffer.data(), sizes[i]);

        // Close input file
        infile.close();
    }
    // Close output file
    outfile.close();

    std::cout << "Dot1_new.dot created successfully." << std::endl;
}

int DOTunpack(std::string Str)
{
   const std::string outputDir = "DOTdata";
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
        cout << "Opened DOT" << endl;
    }

    //---------------------------------------------------------

    //Header header;
    //inputFile.seekg(std::ios::beg);
    //inputFile.read(reinterpret_cast<char*>(&header), sizeof(header));

    extractFiles(inputFile, outputDir);

    // Close the input file
    inputFile.close();

   return 1;
}
int main( int argc,      // Number of strings in array argv
          char *argv[])   // Array of command-line argument strings
{
    //Print debug data
    cout << "XMEN Mutant Academy DOT1 Extractor/Packer" << endl;
    cout << "Input either any DOT1 archive to extract" << endl;
    cout << "Or *.dhed to pack back" << endl;
    cout << "Example: app.exe filename " << endl;


    if (argc <= 1)
    {
        return 0;
    }
    //int DOTMode = std::stoi(argv[2]);
    int DOTMode = 0; //Unpack by default

    std::string input(argv[1]); //Got the filename argument
    base_filename = input.substr(input.find_last_of("/\\") + 1);

    std::string::size_type const p(base_filename.find_last_of('.'));
    fileNoExt = base_filename.substr(0, p);
    fileExt = base_filename.substr(base_filename.find_last_of('.') + 1);

    //Unpacking or Repacking
    if (fileExt == "dhed" || fileExt == "DHED")
    {
        DOTMode = 1;
    }

    if (DOTMode == 0){
        //Unpack
        DOTunpack(input);
    }
    else if (DOTMode == 1)
    {
        //Pack here
        DOTpack();
    }

   return 0;
}

