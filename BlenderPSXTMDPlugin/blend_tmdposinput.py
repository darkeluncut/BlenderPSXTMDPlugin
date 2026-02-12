bl_info = {
    "name": "TMD Pos Importer",
    "author": "Elm",
    "version": (0, 2),
    "blender": (2, 80, 0),
    "location": "File > Import",
    "description": "Import TMD Pos files",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export",
}


import bpy
import bmesh
import struct
import os
import math
import mathutils
from bpy_extras.image_utils import load_image
from bpy_extras.io_utils import unpack_list, unpack_face_list
from math import pi, ceil, degrees, radians, copysign
from mathutils import Vector
from enum import Enum

from bpy.props import (
        BoolProperty,
        EnumProperty,
        FloatProperty,
        StringProperty,
        )
from bpy_extras.io_utils import (
        ImportHelper,
        ExportHelper,
        orientation_helper,
        axis_conversion,
        )

from argparse import Namespace
from typing import Any

@orientation_helper(axis_forward='Y', axis_up='Z')

class ByteBuffer:
    def __init__(self, data):
        self.data = data
        self.position = 0        

    def seek(self, offset):
        self.position = offset 

    def read_byte(self):
        value = self.data[self.position]
        self.position += 1
        return value

    def read_short(self):
        value = struct.unpack_from('h', self.data, self.position)[0]
        self.position += 2
        return value

    def read_int(self):
        value = struct.unpack_from('i', self.data, self.position)[0]
        self.position += 4
        return value


def read_tmdpos(context, filepath):
    if not filepath:
        raise ValueError("Filepath is not provided")

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    fname = os.path.basename(filepath)

    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    sorted_objects = sorted(objects, key=lambda obj: int(obj.name))
    mesh_count = 0

    for obj in sorted_objects:
        if obj.type == 'MESH':
            mesh_count += 1


    objpostbl = []
    objrottbl = []
    position_scale = 1.0 #100.0 / 32767.0
    rotation_scale = 1.0 #180.0 / 32767.0

    with open(filepath, 'rb') as file:
        data = file.read()

        byte_buffer = ByteBuffer(data)
        for i in range(mesh_count):
            rot_x = byte_buffer.read_short()
            rot_y = byte_buffer.read_short()
            rot_z = byte_buffer.read_short()
            rot_x = math.radians(rot_x * rotation_scale)
            rot_y = math.radians(rot_y * rotation_scale)
            rot_z = math.radians(rot_z * rotation_scale)
            tu = (rot_x, rot_y, rot_z)
            objrottbl.append(tu)

            pos_x = byte_buffer.read_short()
            pos_y = byte_buffer.read_short()
            pos_z = byte_buffer.read_short()
            tu = (pos_x*position_scale, pos_y*position_scale, pos_z*position_scale)
            objpostbl.append(tu)

    #Got everything
    #Set it
    for i, obj in enumerate(sorted_objects):
        # Set the rotation values
        tu = objrottbl[i]
        obj.rotation_euler[0] = tu[0]
        obj.rotation_euler[1] = tu[1]
        obj.rotation_euler[2] = tu[2]

        # Set the position values
        tu = objpostbl[i]
        obj.location[0] = tu[0]
        obj.location[1] = tu[1]
        obj.location[2] = tu[2]

    bpy.context.view_layer.update()

    
def tmdpos_save(context, filepath):

    if not filepath:
        raise ValueError("Filepath is not provided")

    fname = os.path.basename(filepath)

    if filepath != "":
        temp_buf = bytearray()
        
        if not filepath.endswith(".tmd_pos"):
            filepath += ".tmd_pos"

        objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
        sorted_objects = sorted(objects, key=lambda obj: int(obj.name))
        
        # Deselect all objects first
        bpy.ops.object.select_all(action='DESELECT')        

        #OBJECTS
        for obj in sorted_objects:
            obj.select_set(True)  # Select the object
            bpy.context.view_layer.objects.active = obj

            # Ensure we are in Object Mode
            if bpy.context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            
    	    # Apply all transformations to the object
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True) #Bake rotation, but store location

            rot_x = 0 #math.degrees(obj.rotation_euler[0]) 
            rot_y = 0 #math.degrees(obj.rotation_euler[1]) 
            rot_z = 0 #math.degrees(obj.rotation_euler[2]) 
            
            # Ensure they fit into a short range
            rot_x = int(round(rot_x))
            rot_y = int(round(rot_y))
            rot_z = int(round(rot_z))

            # Ensure they fit into the short range by clamping
            rot_x = max(-32768, min(32767, int(round(rot_x))))
            rot_y = max(-32768, min(32767, int(round(rot_y))))
            rot_z = max(-32768, min(32767, int(round(rot_z))))

            temp_buf.extend(struct.pack('<hhh', rot_x, rot_y, rot_z))

            pos_x = obj.location[0] 
            pos_y = obj.location[1] 
            pos_z = obj.location[2] 

            # Ensure they fit into the short range by clamping
            pos_x = max(-32768, min(32767, int(round(pos_x))))
            pos_y = max(-32768, min(32767, int(round(pos_y))))
            pos_z = max(-32768, min(32767, int(round(pos_z))))

            obj.location[0] = 0
            obj.location[1] = 0
            obj.location[2] = 0

            # Pack the position values into the bytearray in little-endian format
            temp_buf.extend(struct.pack('<hhh', pos_x, pos_y, pos_z))

        file = open(filepath,'wb')
        file.write(temp_buf)
        file.close()




# Operator definition
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator

class ImportTMDPos(Operator, ImportHelper):
    bl_idname = "import_scene.tmd_pos"
    bl_label = "Import TMD Pos"
    filename_ext = ".tmd_pos"

    def execute(self, context):
        filepath = self.filepath
        read_tmdpos(context, filepath)
        
        return {'FINISHED'}

class ExportTMDPos(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.tmd_pos"
    bl_label = 'Export TMD Pos'
    filename_ext = ".tmd_pos"

    def execute(self, context):
        filepath = self.filepath
        tmdpos_save(context, filepath)
        return {'FINISHED'}

def menu_func_importtmdpos(self, context):
    self.layout.operator(ImportTMDPos.bl_idname, text="TMDPos (.tmd_pos)")

def menu_func_exporttmdpos(self, context):
    self.layout.operator(ExportTMDPos.bl_idname, text="TMDPos (.tmd_pos)")


def register():
    bpy.utils.register_class(ImportTMDPos)
    bpy.utils.register_class(ExportTMDPos)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_importtmdpos)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_exporttmdpos)


def unregister():
    bpy.utils.unregister_class(ImportTMDPos)
    bpy.utils.unregister_class(ExportTMDPos)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_importtmdpos)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_exporttmdpos)

    
# This allows you to run the script directly from Blender's text editor to test the addon.
if __name__ == "__main__":
    register()
