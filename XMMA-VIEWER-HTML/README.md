After you unpack WAD and find and unpack DOT related to the character or level - in DOTdata there will be multiple files: file_00000, file_00001, etc. without extensions.
+.TMD_POS - default position file is usually the last one for both levels and characters.
+.TMD - model will usually be file_00001 or file_00002. It can be recognized by 'magic' hex header 41.
+.TMD_ANM - animations file is usually right above TMD one. Not present in the level DOT file.
+.TIM - textures are usually between TMD and TMD_POS. Sometimes a packed animated tim is present as the top file/files, but they are currently unusable.

Add the extensions accordingly, load into viewer in TMD, TMD_POS, TIMs, [TMD_ANM] order. Viewer can handle loading TIMs in batch and without extensions for convenience.

XMMA is tricky as it calculates hierarchical behaviour with TMDs for animations by adding dummy point/bones and using hardcoded lookup tables. 
Since I want it to be flexible - I simulate the rules without hardcoding, but it might break animations on edge cases.