X-Men MA - DOT1 Console Tool - 0.11

What is it:
Console only tool that can unpack and repack PSX X-MEN Mutant Academy inner DOT1 archives inside of WAD.WAD file.

How to unpack:
Put XMMA_DOT1Console.exe near a file (presumably extracted from WAD).
Use "XMMA_DOT1Console.exe filename" in console/terminal.

It detaches the header into filename.dhed and unpacks binary files into data.

How to pack:
Use "XMMA_DOT1Console.exe filename.dhed" in console/terminal.

It combines that back into Dot1_new.dot that you can rename/move to wherever it needs to go.

You should be able to replace inner data (TMD, TIM, etc. with no issues, resizing included).
It is technically possible to add more files and modify filename.dhed, but I found that it breaks things.

Probably can work with MA2 as well, but not guaranteed.

Provided as is.

0.1 - Initial release; 0.11 - Bugfix 
