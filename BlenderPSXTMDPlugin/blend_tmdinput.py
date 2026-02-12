bl_info = {
    "name": "TMD Importer",
    "author": "Elm",
    "version": (0, 2),
    "blender": (2, 80, 0),
    "location": "File > Import",
    "description": "Import TMD files",
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

def flip(v):
    return (v[0],v[2],v[1]) 

def flip_all(v):
    return [y for y in [flip(x) for x in v]]


class dotdict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__


class Vec3:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

class Vec3f:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z

class Material:
    def __init__(self, red=None, green=None, blue=None, transparent=False, CLUT=None, TXB=None):
        if red is not None and green is not None and blue is not None:
            self.ambient = Vec3f((red & 0xff) / 255.0,
                                 (green & 0xff) / 255.0,
                                 (blue & 0xff) / 255.0)
            self.diffuse = Vec3f((red & 0xff) / 255.0,
                                 (green & 0xff) / 255.0,
                                 (blue & 0xff) / 255.0)
            self.specular = Vec3f(0.0, 0.0, 0.0)
            self.dissolve = 0.5 if transparent else 1.0
            self.tx_map = None
            self.ID = f"{red:04x}.{green:04x}.{blue:04x}.{self.dissolve:.1f}"
        elif CLUT is not None and TXB is not None:
            self.dissolve = 1.0
            self.ambient = Vec3f(1.0, 1.0, 1.0)
            self.diffuse = Vec3f(1.0, 1.0, 1.0)
            self.specular = Vec3f(0.0, 0.0, 0.0)
            self.tx_map = f"_t{CLUT}_t{TXB}.png"
            self.ID = self.tx_map

    def __hash__(self):
        return hash(self.ID)

class ModeBitFlags:
    ENTITY_TYPE_MASK = 0b111 << 0  # bits 0-2
    # Define bit positions using hexadecimal
    BRIGHTNESS = 0x1      # 0th bit (hex 1)
    TRANSPARENCY = 0x2    # 1st bit (hex 2)
    TEXTURE = 0x4         # 2nd bit (hex 4)
    QUAD = 0x8            # 3rd bit (hex 8)
    GOURAUD = 0x10        # 4th bit (hex 10)
    BIT_5 = 0x20          # 5th bit (hex 20)
    
    # Entity type masks
    POLYGON = 0b001  # 001 = Polygon (triangle, quadrilateral)
    LINE = 0b010     # 010 = Straight line
    SPRITE = 0b011   # 011 = Sprite

    def __init__(self, mode):
        self.mode = mode

    @property
    def entity_type(self):
        return self.mode & self.ENTITY_TYPE_MASK

    @property
    def is_brightness(self):
        return bool(self.mode & self.BRIGHTNESS)

    @property
    def is_transparency(self):
        return bool(self.mode & self.TRANSPARENCY)

    @property
    def is_texture(self):
        return bool(self.mode & self.TEXTURE)

    @property
    def is_quad(self):
        return bool(self.mode & self.QUAD)

    @property
    def is_gouraud(self):
        return bool(self.mode & self.GOURAUD)

    @property
    def is_bit_5(self):
        return bool(self.mode & self.BIT_5)

    def get_entity_type_name(self):
        entity_type = self.entity_type
        if entity_type == self.POLYGON:
            return "Polygon (triangle, quadrilateral)"
        elif entity_type == self.LINE:
            return "Straight line"
        elif entity_type == self.SPRITE:
            return "Sprite"
        else:
            return "Unknown"
        
    def __str__(self):
        return (
            f"Brightness: {self.is_brightness}\n"
            f"Transparency: {self.is_transparency}\n"
            f"Texture: {self.is_texture}\n"
            f"Quad: {self.is_quad}\n"
            f"Gouraud: {self.is_gouraud}\n"
            f"Bit 5: {self.is_bit_5}"
        )
#usage flags = ModeBitFlags(mode)

class FlagBitFlags:
    # Define bit positions using hexadecimal
    LIGHT_SOURCE = 0x1      # 0th bit (hex 1)
    TWO_SIDED = 0x2         # 1st bit (hex 2)
    GRADATION = 0x4         # 2nd bit (hex 4)

    def __init__(self, flag):
        self.flag = flag

    @property
    def is_light_source(self):
        return bool(self.flag & self.LIGHT_SOURCE)

    @property
    def is_two_sided(self):
        return bool(self.flag & self.TWO_SIDED)

    @property
    def is_gradation(self):
        return bool(self.flag & self.GRADATION)

    def __str__(self):
        return (
            f"Do not calculate light sourcing: {self.is_light_source}\n"
            f"Polygon is double sided: {self.is_two_sided}\n"
            f"Gradated: {self.is_gradation}"
        )

# Example usage
#flags = Flag(flag_value)

class ClutCoordinates:
    def __init__(self, cba):
        self.cba = cba

    @property
    def clut_x(self):
        return (self.cba % 64) * 16

    @property
    def clut_y(self):
        return self.cba // 64

    def __str__(self):
        return f"clutX: {self.clut_x}, clutY: {self.clut_y}"

# Example usage
#clut_coords = ClutCoordinates(cba_value)

class TexturePageAttributes:
    def __init__(self, tsb):
        self.tsb = tsb

    @property
    def texture_page(self):
        return self.tsb & 0x1F  # Extract bits 0-4

    @property
    def semitransparency_rate(self):
        return (self.tsb >> 5) & 0x03  # Extract bits 5-6 (0..3)

    @property
    def colour_mode(self):
        return (self.tsb >> 7) & 0x03  # Extract bits 7-8 (0..2)

    def __str__(self):
        return (
            f"Texture Page: {self.texture_page}\n"
            f"Semitransparency Rate: {self.semitransparency_rate}\n"
            f"Colour Mode: {self.colour_mode}"
        )

# Example usage

#attributes = TexturePageAttributes(tsb_value)

class TexturePageExtractor:
    def __init__(self, node):
        self.node = node

    def extract_unique_texture_pages(self):
        unique_texture_pages = set()
        for face in self.node.faces:
            texture_page = face.TXB & 0x1F  # Extract bits 0-4 for texture_page
            unique_texture_pages.add(texture_page)
        return unique_texture_pages
#usage
# # Extract unique texture pages
#extractor = TexturePageExtractor(node)
#unique_texture_pages = extractor.extract_unique_texture_pages()    

class PrimitiveType(Enum):
    NoneType = 0
    Triangle = 1
    Quad = 2
    StraightLine = 3
    Sprite = 4
    StripMesh = 5

class TmdPacket:
    @staticmethod
    def build(data, flag, mode, ilen, primitiveType):
        flagmode = (mode + (flag << 8))

        packet_classes = {
            0x0020: FFPacket,
            0x0030: GFPacket,
            0x0024: FTPacket,
            0x0121: NFPacket,
            0x0034: GTPacket,
            0x0036: GTPacket
        }

        if flagmode in packet_classes:
            return packet_classes[flagmode](data, primitiveType)
        else:
            raise ValueError(f"Unrecognized flag: 0x{flagmode:x} ({ilen})")


class Primitive:
    def __init__(self, data):
        self.olen = data.read_byte()
        self.ilen = data.read_byte()
        self.flag = data.read_byte()
        self.mode = data.read_byte()

        modebits = ModeBitFlags(self.mode)
        entity_type = modebits.entity_type
        self.is_gouraud = modebits.is_gouraud

        #Set entity
        self.primitiveType = PrimitiveType.NoneType
        if entity_type == ModeBitFlags.POLYGON:
            if not modebits.is_quad:
                #Triangle
                self.primitiveType = PrimitiveType.Triangle
            else:
                #Quad    
                self.primitiveType = PrimitiveType.Quad
        elif entity_type == ModeBitFlags.LINE:
            #Line
            self.primitive_type = PrimitiveType.StraightLine        
        elif entity_type == ModeBitFlags.SPRITE:
            #Sprite
            self.primitive_type = PrimitiveType.Sprite    


        self.packet = TmdPacket.build(data, self.flag, self.mode, self.ilen, self.primitiveType)

        


class FFPacket: 
    #Flat Shading No texture
    def __init__(self, data, primitiveType):
        self.is_uvs = False
        self.is_rgb = True

        self.red = data.read_byte()
        self.green = data.read_byte()
        self.blue = data.read_byte()
        self.mode = data.read_byte()        
        self.normal1 = data.read_short()
        self.vert1 = data.read_short()
        self.vert2 = data.read_short()
        self.vert3 = data.read_short()
        if primitiveType == PrimitiveType.Quad:
            self.vert4 = data.read_short()
            data.read_short() # Padding

class GFPacket:
    #Gourad Shading No Texture
    def __init__(self, data, primitiveType):
        self.is_uvs = False
        self.is_rgb = True

        self.red = data.read_byte()
        self.green = data.read_byte()
        self.blue = data.read_byte()
        self.mode = data.read_byte()
        self.normal1 = data.read_short()
        self.vert1 = data.read_short()
        self.normal2 = data.read_short()
        self.vert2 = data.read_short()
        self.normal3 = data.read_short()
        self.vert3 = data.read_short()
        if primitiveType == PrimitiveType.Quad:
            self.normal4 = data.read_short()
            self.vert4 = data.read_short()

class FTPacket:
    #Flat Shading Texture
    def __init__(self, data, primitiveType):
        self.is_uvs = True
        self.is_rgb = False

        self.u1 = data.read_byte()
        self.v1 = data.read_byte()
        self.CBA = data.read_short()
        self.u2 = data.read_byte()
        self.v2 = data.read_byte()
        self.TSB = data.read_short()
        self.u3 = data.read_byte()
        self.v3 = data.read_byte()
        data.read_short()  # padding
        if primitiveType == PrimitiveType.Quad:
            self.u4 = data.read_byte()
            self.v4 = data.read_byte()
            data.read_short() # padding
        self.normal1 = data.read_short()
        self.vert1 = data.read_short()
        self.vert2 = data.read_short()
        self.vert3 = data.read_short()
        if primitiveType == PrimitiveType.Quad:
            self.vert4 = data.read_short()
            data.read_short() # padding

class GTPacket:
    #Gourad Shading Textured
    def __init__(self, data, primitiveType):
        self.is_uvs = True
        self.is_rgb = False

        self.u1 = data.read_byte()
        self.v1 = data.read_byte()
        self.CBA = data.read_short()
        self.u2 = data.read_byte()
        self.v2 = data.read_byte()
        self.TSB = data.read_short()
        self.u3 = data.read_byte()
        self.v3 = data.read_byte()
        data.read_short()  # padding
        if primitiveType == PrimitiveType.Quad:
            self.u4 = data.read_byte()
            self.v4 = data.read_byte()
            data.read_short() # padding
        self.normal1 = data.read_short()
        self.vert1 = data.read_short()
        self.normal2 = data.read_short()
        self.vert2 = data.read_short()
        self.normal3 = data.read_short()
        self.vert3 = data.read_short()
        if primitiveType == PrimitiveType.Quad:
            self.normal4 = data.read_short()
            self.vert4 = data.read_short()

class NFPacket:
    #No Shading Flat No Texture
    def __init__(self, data, primitiveType):
        self.red = data.read_byte()
        self.green = data.read_byte()
        self.blue = data.read_byte()
        self.mode = data.read_byte()
        self.vert1 = data.read_short()
        self.vert2 = data.read_short()
        self.vert3 = data.read_short()
        if primitiveType == PrimitiveType.Quad:
            self.vert4 = data.read_short()
        else:
            data.read_short() #padding


class ByteBuffer:
    def __init__(self, data, offset):
        self.data = data
        self.position = 28
        self.inpos = offset

    def seek(self, offset):
        self.position = offset - self.inpos + 12

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

def fixed_16_to_float(value):
    return value if value == 0 else value / 4096.0

def float_to_fixed_16(value):
    return value if value == 0 else int(round(value * 4096)).to_bytes(1, "little", signed=True)[0]

class Model:
    def __init__(self, data, flags, offset, name):
        self.name = name
        self.verts = []
        self.normals = []
        self.primitives = []
        self.flags = flags
        self.vertAddress = struct.unpack_from('i', data, 0)[0] 
        self.nVert = struct.unpack_from('i', data, 4)[0]
        self.normalAddress = struct.unpack_from('i', data, 8)[0]
        self.nNorm = struct.unpack_from('i', data, 12)[0]
        self.primitiveAddress = struct.unpack_from('i', data, 16)[0]
        self.nPrimitive = struct.unpack_from('i', data, 20)[0]
        self.scale = struct.unpack_from('i', data, 24)[0]

    def populate(self, data, offset):
        if self.flags != 0:
            print(f"Unrecognized flags: {self.flags}")
            return
        print("INPUT MODEL")
        
        print(f"vertAddress: 0x{self.vertAddress:x}")
        print(f"normalAddress: 0x{self.normalAddress:x}")
        print(f"primitiveAddress: 0x{self.primitiveAddress:x}")

        byte_buffer = ByteBuffer(data, offset)

        byte_buffer.seek(self.vertAddress)
        for i in range(self.nVert):
            x = byte_buffer.read_short()
            y = byte_buffer.read_short()
            z = byte_buffer.read_short()
            xs = x 
            ys = y 
            zs = z 
            t = (xs, ys, zs)
            self.verts.append(t)
            byte_buffer.read_short()  # pad


        byte_buffer.seek(self.normalAddress)
        for i in range(self.nNorm):
            x = byte_buffer.read_short()
            y = byte_buffer.read_short()
            z = byte_buffer.read_short()
            xs = x*(2**3)
            ys = y*(2**3)
            zs = z*(2**3)

            t = (xs, ys, zs)
            self.normals.append(t)
            byte_buffer.read_short()  # pad

        byte_buffer.seek(self.primitiveAddress)

        for i in range(self.nPrimitive):
            p = Primitive(byte_buffer)
            self.primitives.append(p)


class TMDParser:
    def __init__(self):
        self.fp = None

    def cb_result(self):
        return True

    def parse(self, objList):
            for model in objList:
                self.parsePart('NODE', model)
                self.parsePart('VRTS', model)
                self.parsePart('NRML', model)
                self.parsePart('FACE', model)                
            return self.cb_result()
                
 
    def parsePart(self, chunk, data):
            if chunk=='NODE':
                self.cb_next()
                name = data.name                
                self.cb_data(chunk, {'name':name})                
            elif chunk=='VRTS':                
                v = []
                v.extend(data.verts)
                self.cb_data(chunk, {'vertices':v})
            elif chunk=='NRML':                
                n = []                
                n.extend(data.normals)
                self.cb_data(chunk, {'normals':n})
            elif chunk=='FACE':                
                faces = []
                rgbs = []
                u,clut,ni,txb = [],[],[],[]                
                polyflag, polymode = [],[]
                is_rgb_f, is_uvs_f, is_gouraud_f, is_quad_f = [],[],[],[]
                for index, face in enumerate(data.primitives):                   
                    #Get quad or tri, rgb or uv
                    if face.primitiveType == PrimitiveType.Quad:
                        is_quad = True
                    else:
                        is_quad = False    

                    is_uvs = face.packet.is_uvs
                    is_rgb = face.packet.is_rgb
                    is_gouraud = face.is_gouraud

                    #Indices
                    if is_quad:
                        t = (face.packet.vert1, face.packet.vert2, face.packet.vert3, face.packet.vert4)
                    else:
                        t = (face.packet.vert1, face.packet.vert2, face.packet.vert3)
                    faces.append(t)

                    #UVs
                    if is_uvs:
                        us1 = face.packet.u1 / 255.0
                        vs1 = (255-face.packet.v1) / 255.0
                        us2 = face.packet.u2 / 255.0
                        vs2 = (255-face.packet.v2) / 255.0
                        us3 = face.packet.u3 / 255.0
                        vs3 = (255-face.packet.v3) / 255.0

                        if is_quad:
                            us4 = face.packet.u4 / 255.0
                            vs4 = (255-face.packet.v4) / 255.0
                            tu = (us1, vs1, us2, vs2, us3, vs3, us4, vs4)
                        else: 
                            tu = (us1, vs1, us2, vs2, us3, vs3)        
                        u.append(tu)

                        clut.append(face.packet.CBA)
                        txb.append(face.packet.TSB)
                    else:
                        if is_quad:
                            tu = (0, 0, 0, 0, 0, 0, 0, 0)
                        else: 
                            tu = (0, 0, 0, 0, 0, 0)        
                        u.append(tu) 

                        clut.append(0)
                        txb.append(0)   


                    #RGBs
                    if is_rgb:
                        col = (face.packet.red, face.packet.green, face.packet.blue)
                        rgbs.append(col)
                    else:
                        col = (0,0,0)
                        rgbs.append(col)
                                

                    #TNI        
                    if is_gouraud:
                        if is_quad:
                            tni = (face.packet.normal1, face.packet.normal2, face.packet.normal3, face.packet.normal4)   
                        else:
                            tni = (face.packet.normal1, face.packet.normal2, face.packet.normal3)  
                    else:
                        tni = (face.packet.normal1)   

                    ni.append(tni)

                    polyflag.append(face.flag)
                    polymode.append(face.mode)

                    is_quad_f.append(is_quad)
                    is_gouraud_f.append(is_gouraud)
                    is_rgb_f.append(is_rgb)
                    is_uvs_f.append(is_uvs)

                self.cb_data(chunk, {'indices':faces, 'uvs':u, 'ni':ni, 'CBA':clut, 'TXB':txb, 'polyflag':polyflag, 'polymode':polymode, 'rgbs':rgbs, 'is_uvs':is_uvs_f, 'is_rgb':is_rgb_f,'is_gouraud':is_gouraud_f,'is_quad':is_quad_f})

        

class TMDList(TMDParser):
    def __init__(self):
        TMDParser.__init__(self)
        self.index = -1
        self.data = dotdict()
        self.data.nodes = []

    def cb_next(self):
        self.data.nodes.append(dotdict())
        parent = self.index
        self.index = len(self.data.nodes)-1
        self.data.nodes[self.index].parent = -1

    def cb_prev(self):
        self.index = self.data.nodes[self.index].parent

    def cb_data(self, chunk, data):
        if self.index != -1:
            node = self.data.nodes[self.index]

        if chunk in ['NODE','MESH','VRTS','NRML']:
            node.update(data)
        elif chunk=='FACE':
            if 'faces' not in node:
                node.faces = []
            node.faces.append(dotdict(data))

    def cb_result(self):
        return self.data


class TMDTree(TMDList):
    def __init__(self):
        TMDList.__init__(self)

    def cb_result(self):
        tree = []
        nodes = self.data.nodes

        for node in nodes:
            node.nodes = []

        for i, node in enumerate(nodes):
            if node.parent == -1:
                tree.append(node)
            else:
                nodes[node.parent].nodes.append(node)
            del node['parent']

        self.data.update({'nodes':tree})
        return self.data


def encode_modeflags(flags):
    encoded_flags = (
        int(flags.is_brightness) |
        (int(flags.is_transparency) << 1) |
        (int(flags.is_texture) << 2) |
        (int(flags.is_quad) << 3) |
        (int(flags.is_gouraud) << 4) |
        (int(flags.is_bit_5) << 5)
    )
    return encoded_flags

def encode_flagflags(flags):
    # Initialize encoded_flags as 0
    encoded_flags = (    
    int(flags.is_light_source) |
        (int(flags.is_two_sided) << 1) |
        (int(flags.is_gradation) << 2)
    )    
    return encoded_flags

def import_mesh(node, parent):
    global material_mapping

    mesh = bpy.data.meshes.new(node.name)
    ob = bpy.data.objects.new(node.name, mesh)
    
    # join face arrays
    faces = []
    for face in node.faces:
        faces.extend(face.indices)


    # create mesh from data
    mesh.from_pydata(node.vertices, [], faces)
    # Ensure mesh update
    mesh.update()    


    # Enable auto smooth
    mesh.use_auto_smooth = True

    split_normals = []
    for face in node.faces:
        for index, ni in enumerate(face.ni):
            nit = ni                

            if face.is_gouraud[index]:
                norm_1 = Vector(node.normals[nit[0]]).normalized()
                norm_2 = Vector(node.normals[nit[1]]).normalized()
                norm_3 = Vector(node.normals[nit[2]]).normalized()
                if face.is_quad[index]:    
                    norm_4 = Vector(node.normals[nit[3]]).normalized()
            else:       
                norm_1 = Vector(node.normals[nit]).normalized()
                norm_2 = Vector(node.normals[nit]).normalized()
                norm_3 = Vector(node.normals[nit]).normalized()
                if face.is_quad[index]:    
                    norm_4 = Vector(node.normals[nit]).normalized()
            
            if face.is_quad[index]:    
                split_normals.extend((norm_1, norm_2, norm_3, norm_4))
            else:
                split_normals.extend((norm_1, norm_2, norm_3))
    
    mesh.update()
    mesh.normals_split_custom_set(split_normals)
    mesh.calc_normals_split() #This is correct

    #---------------------------------------------------------------------------------------------
    #Set RGBs
    for face in node.faces:
        for index, poly in enumerate(mesh.polygons):
            if face.is_rgb[index]:
                # Ensure the mesh has a vertex color layer
                if not mesh.vertex_colors:
                    mesh.vertex_colors.new(name="Col")

                color_layer = mesh.vertex_colors.active.data
                color = face.rgbs[index]

                for loop_index in poly.loop_indices:
                    color_layer[loop_index].color = (*color, 1.0) 
    #---------------------------------------------------------------------------------------------
    #Set materials
    # Collect existing materials with the "TPage" custom property
    unique_materials = {mat["TPage"]: mat for mat in bpy.data.materials if "TPage" in mat}

    mesh_faces = mesh.polygons
    for face in node.faces:
        for orig_face_index, TXBdata in enumerate(face.TXB):
            if face.is_uvs[orig_face_index]:
                txb_value = TXBdata
                mesh_face = mesh_faces[orig_face_index]

                tsb_temp = txb_value 
                tattr = TexturePageAttributes(tsb_temp)
                tpage = tattr.texture_page
        

                # Find the material with the matching "TPage" property
                mat = unique_materials.get(tpage)

                if mat is None:        
                    #Create here
                    # Set the dimensions of the image
                    width = 256
                    height = 256

                    # Create a new image
                    texture_prefix = "TPage_"
                    texname = f"{texture_prefix}{tpage}"
                    image = bpy.data.images.new(texname, width=width, height=height)

                    print(f"Texname: {texname}")


                    # Fill the image with transparent pixels
                    transparent_color = (1.0, 1.0, 1.0, 1.0)  # RGBA values 
                    image.pixels[:] = [transparent_color[i % 4] for i in range(width * height * 4)]

                    # Define the material properties
                    dissolve_value = 1.0
                    ambient_color = (1.0, 1.0, 1.0, 1.0)  # RGBA values for ambient (assuming fully opaque)
                    diffuse_color = (1.0, 1.0, 1.0, 1.0)  # RGBA values for diffuse (assuming fully opaque)
                    specular_color = 0.0  # RGBA values for specular (assuming fully opaque)

                    # Create a new material
                    mat = bpy.data.materials.new(name=texname)
                    mat["TPage"] = tpage

                    # Enable use of nodes
                    mat.use_nodes = True

                    # Clear all nodes to start clean
                    nodes = mat.node_tree.nodes
                    nodes.clear()

                    # Add principled shader node
                    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
                    principled.inputs['Alpha'].default_value = dissolve_value
                    if 'Specular' in principled.inputs:
                        # Assign RGB values (first three components) for NodeSocketColor
                        principled.inputs['Specular'].default_value = specular_color
                    else:
                        # Print error message or handle the case where 'Specular' input is not found
                        print("'Specular' input not found in Principled BSDF node. Adding a new input...")
            
                    # Set ambient and diffuse colors
                    principled.inputs['Base Color'].default_value = ambient_color[:4]  # Base color RGB
                    principled.inputs['Base Color'].default_value = diffuse_color[:4]  # Base color RGB

                    # Add a texture node
                    tex_image = nodes.new(type='ShaderNodeTexImage')
                    tex_image.image = image
                    tex_image.location = (-200, 200)  # Optional: Move node for better organization

                    # Link the texture node to the principled shader node
                    links = mat.node_tree.links
                    links.new(tex_image.outputs['Color'], principled.inputs['Base Color'])

                    # Link the principled shader to the output node
                    output = nodes.new(type='ShaderNodeOutputMaterial')
                    links.new(principled.outputs['BSDF'], output.inputs['Surface'])

                    print(f"Material created: {mat.name} with TPage: {tpage}")

                    # Append the new material to unique_materials
                    unique_materials[tpage] = mat
        
                # Check if the material is already linked to the object
                mat_name = mat.name
                if mat_name not in ob.data.materials:
                    ob.data.materials.append(mat)
                    print(f"Added material '{mat_name}' to object '{ob.name}'")

                # Assign material index to the face
                mesh_face.material_index = ob.data.materials.find(mat_name)
    
    # Update the object after assigning materials
    ob.data.update()
    #----------------------------------------------------------------------------------------------------
    #UVS
    mesh = ob.data



    uvlist = []
    # Ensure mesh has UV layers
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")  # Create a new UV layer if none exists

    # Ensure the uv_layer is the active UV layer
    uv_layer = mesh.uv_layers.active.data  # Access the active UV layer

    for face in node.faces:
        # Extract UV coordinates (tu) for the current face
        for index, tu in enumerate(face.uvs):
            # Each 'tu' is a tuple of (u1, v1, u2, v2, u3, v3)
            uvlist.extend([(tu[i], tu[i + 1]) for i in range(0, len(tu), 2)])
    
        # Iterate over each loop in the mesh and assign UV coordinates
        for face_index, poly in enumerate(mesh.polygons):
            if face.is_uvs[face_index]:
                for loop_index in poly.loop_indices:
                    uv_layer[loop_index].uv = uvlist[loop_index]
    
    #Store additional data
    #---------------------------------------------------------------------------------------------
    attr_name = "FaceModeFlags"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')


    for nfce in node.faces:
        for face_index, PModeData in enumerate(nfce.polymode):
            flags = ModeBitFlags(PModeData)
            encoded_flags = encode_modeflags(flags)

            if mesh.attributes.get(attr_name):
                
                attr_data = mesh.attributes[attr_name].data[face_index]
                attr_data.value = encoded_flags
    #------------------------------
    attr_name = "FaceFlagFlags"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    for nfce in node.faces:
        for face_index, PModeData in enumerate(nfce.polyflag):
            flags = FlagBitFlags(PModeData)
            encoded_flags = encode_flagflags(flags)

            if mesh.attributes.get(attr_name):
                
                attr_data = mesh.attributes[attr_name].data[face_index]
                attr_data.value = encoded_flags
    #------------------------------
    attr_name = "Clut"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    for nfce in node.faces:
        for face_index, PModeData in enumerate(nfce.CBA):
            if nfce.is_uvs[face_index]:
                if mesh.attributes.get(attr_name):
                
                    attr_data = mesh.attributes[attr_name].data[face_index]
                    attr_data.value = PModeData
    #------------------------------
    attr_name = "TXB"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    for nfce in node.faces:
        for face_index, PModeData in enumerate(nfce.TXB):
            if nfce.is_uvs[face_index]:
                if mesh.attributes.get(attr_name):
                
                    attr_data = mesh.attributes[attr_name].data[face_index]
                    attr_data.value = PModeData
    
    
    # Ensure mesh update
    mesh.update()

    return ob

def import_node_recursive(node, parent=None):

    ob = None

    if 'vertices' in node and 'faces' in node:
        ob = import_mesh(node, parent)
    elif node.name:
        ob = bpy.data.objects.new(node.name, None)

    if ob:
        bpy.context.scene.collection.objects.link(ob)

        if parent:
            ob.parent = parent

      
    for x in node.nodes:
        import_node_recursive(x, parent)


def read_tmd(context, filepath):
    if not filepath:
        raise ValueError("Filepath is not provided")

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    fname = os.path.basename(filepath)


    with open(filepath, 'rb') as file:
        data = file.read()

    objList = []
    offset = 12

    id, flags, nObj = struct.unpack('iii', data[:12])
    print(f"id: {id}")
    print(f"id: {nObj}")

    for indexb in range(nObj):
        print(f"reading model: {indexb}")

        name = str(indexb)
        model_data = data[offset:]
        model = Model(model_data, flags, offset, name)
        model.populate(model_data, offset)
        objList.append(model)

        offset += 28  # Update offset for the next model

    #Got everything
    tmdata = TMDTree().parse(objList)
    #Create blank holder
    ob = bpy.data.objects.new(fname, None)
    bpy.context.scene.collection.objects.link(ob)

    #scale_factor = 1/100.0
    #scale_matrix = mathutils.Matrix.Scale(scale_factor, 4)
    # Create a flipping matrix along X axis
    #flip_matrix = mathutils.Matrix.Scale(-1.0, 4)
    #rotation_matrix = mathutils.Matrix.Rotation(math.radians(90), 4, 'X')
    # Combine the matrices (rotation, then flip, then scale)
    #transformation_matrix = rotation_matrix @ flip_matrix @ scale_matrix
    #ob.matrix_world = transformation_matrix

    #
    import_node_recursive(tmdata,ob)

def write_bin(value):
    return struct.pack("<h",value)

def write_int(value):
    return struct.pack("<i",value)

def write_float(value):
    return struct.pack('<f', value)

def write_short(value):
    return value.to_bytes(2, byteorder='little')

def write_vertex(x, y, z):
    vertex_data = bytearray()

    vertex_data += write_float(x)[:2]  # First 2 bytes for x
    vertex_data += write_float(y)[:2]  # Next 2 bytes for y
    vertex_data += write_float(z)[:2]  # Next 2 bytes for z
    vertex_data += b'\x00\x00'  # 2 bytes of filler
    return vertex_data

def truncate_float(f, decimal_places):
    factor = 10 ** decimal_places
    return math.trunc(f * factor) / factor

def getLoopNormal(normal: Vector):
    norm = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    normalized_normal = (normal[0] / norm, normal[1] / norm, normal[2] / norm)
    x = truncate_float(normalized_normal[0], 4)
    y = truncate_float(normalized_normal[1], 4)
    z = truncate_float(normalized_normal[2], 4)


    return x, y, z

def vector_dup(vec1, vec2, tolerance):
    distance = math.sqrt((vec1[0] - vec2[0]) ** 2 + (vec1[1] - vec2[1]) ** 2 + (vec1[2] - vec2[2]) ** 2)
    
    return distance <= tolerance

def dropFloat(float_value):
    result = round(float_value * 1000000, 1) / 100
    i_result = int(result)/10000
    return i_result

def packNormal(normal: Vector):
 # Convert standard normal to constant-L1 normal
    assert len(normal) == 3

    norm = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    #norm = 1
    if norm == 0:
        # Handle the case where the norm is zero
        normalized_normal = (0.0, 0.0, 0.0)
    else:
        normalized_normal = (normal[0] / norm, normal[1] / norm, normal[2] / norm)        

    # Scale and convert to 16-bit fixed-point integers
    packed_x = int(round(normalized_normal[0],8) * 4096)
    packed_y = int(round(normalized_normal[1],8) * 4096)
    packed_z = int(round(normalized_normal[2],8) * 4096)
    
    # Clamp values to ensure they fit within 16-bit signed integer range
    packed_x = max(-32767, min(packed_x, 32767))
    packed_y = max(-32767, min(packed_y, 32767))
    packed_z = max(-32767, min(packed_z, 32767))

    return packed_x, packed_y, packed_z


def write_normal(normal):
    vertex_data = bytearray()
    x,y,z = normal

    vertex_data.extend([x & 0xFF, (x >> 8) & 0xFF])
    vertex_data.extend([y & 0xFF, (y >> 8) & 0xFF])
    vertex_data.extend([z & 0xFF, (z >> 8) & 0xFF])
    vertex_data += b'\x00\x00'  # 2 bytes of filler
    return vertex_data

def write_byte(value):
    return struct.pack('<B', value)


def Write_FFPacket(data, mesh, nit_table, vit_table, n_index, is_quad, mode): 
    #Flat Shading No texture
        color_layer = mesh.vertex_colors.active.data
        color = color_layer[0].color #loop_index is 0, because color is per face
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)
        data.append(r)
        data.append(g)
        data.append(b)        
        data += write_byte(mode) #padding
        
        if is_quad:
            vmul = 4
        else:
            vmul = 3

        tni_pos = nit_table[n_index*vmul+0]    
        data += write_short(tni_pos)    #only first normal

        if is_quad:
            tvi_pos = vit_table[n_index*vmul+0]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+3]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+2]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+1]
            data += write_short(tvi_pos)    
        else:            
            tvi_pos = vit_table[n_index*vmul+0]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+2]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+1]
            data += write_short(tvi_pos)    

def Write_GFPacket(data, mesh, nit_table, vit_table, n_index, is_quad, mode): 
    #Gourad Shading No Texture
        color_layer = mesh.vertex_colors.active.data
        color = color_layer[0].color #loop_index is 0, because color is per face
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)
        data.append(r)
        data.append(g)
        data.append(b)        
        data += write_byte(mode) #padding

        if is_quad:
            vmul = 4
        else:
            vmul = 3

        if is_quad:
            tni_pos = nit_table[n_index*vmul+0]    
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+3]    
            tvi_pos = vit_table[n_index*vmul+3]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+2]    
            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+1]    
            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    
        else:
            tni_pos = nit_table[n_index*vmul+0]    
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+2]    
            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+1]    
            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    


def Write_FTPacket(data, mesh, nit_table, vit_table, n_index, is_quad, mode): 
    #Flat Shading Texture
        uv_layer = mesh.loops.layers.uv.active
        face = mesh.faces[n_index]
        clut = mesh.faces.layers.int.get("Clut")
        txb = mesh.faces.layers.int.get("TXB")

        loop = face.loops[0]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        clutval = mesh.faces[face.index][clut]                
        data += write_short(clutval)

        loop = face.loops[1]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        txbval = mesh.faces[face.index][txb]                
        data += write_short(txbval)

        loop = face.loops[2]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        data += b"\x00\x00" #pad
        if is_quad:
            loop = face.loops[3]                
            uv = loop[uv_layer].uv
            u = int(uv.x*255)
            data += write_byte(u)   
            v = 255 - int(255 * uv.y)
            data += write_byte(v)

            data += b"\x00\x00" #pad

        if is_quad:
            vmul = 4
        else:
            vmul = 3

        tni_pos = nit_table[n_index*vmul+0]    
        data += write_short(tni_pos)    #only first normal

        if is_quad:
            tvi_pos = vit_table[n_index*vmul+0]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+3]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+2]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+1]
            data += write_short(tvi_pos)    
            data += b"\x00\x00" #pad
        else:            
            tvi_pos = vit_table[n_index*vmul+0]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+2]
            data += write_short(tvi_pos)    
            tvi_pos = vit_table[n_index*vmul+1]
            data += write_short(tvi_pos)    

def Write_GTPacket(data, mesh, nit_table, vit_table, n_index, is_quad, mode): 
    #Gourad Shading Textured
        uv_layer = mesh.loops.layers.uv.active
        face = mesh.faces[n_index]
        clut = mesh.faces.layers.int.get("Clut")
        txb = mesh.faces.layers.int.get("TXB")

        loop = face.loops[0]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        clutval = mesh.faces[face.index][clut]                
        data += write_short(clutval)

        loop = face.loops[1]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        txbval = mesh.faces[face.index][txb]                
        data += write_short(txbval)

        loop = face.loops[2]                
        uv = loop[uv_layer].uv
        u = int(uv.x*255)
        data += write_byte(u)   
        v = 255 - int(255 * uv.y)
        data += write_byte(v)

        data += b"\x00\x00" #pad
        if is_quad:
            loop = face.loops[3]                
            uv = loop[uv_layer].uv
            u = int(uv.x*255)
            data += write_byte(u)   
            v = 255 - int(255 * uv.y)
            data += write_byte(v)

            data += b"\x00\x00" #pad


        if is_quad:
            vmul = 4
        else:
            vmul = 3

        if is_quad:
            tni_pos = nit_table[n_index*vmul+0]    
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+3]    
            tvi_pos = vit_table[n_index*vmul+3]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+2]    
            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+1]    
            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    
        else:
            tni_pos = nit_table[n_index*vmul+0]    
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+2]    
            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    

            tni_pos = nit_table[n_index*vmul+1]    
            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tni_pos)    
            data += write_short(tvi_pos)    


def Write_NFPacket(data, mesh, nit_table, vit_table, n_index, is_quad, mode): 
    #No Shading Flat No Texture
        color_layer = mesh.vertex_colors.active.data
        color = color_layer[0].color #loop_index is 0, because color is per face
        r = int(color[0] * 255)
        g = int(color[1] * 255)
        b = int(color[2] * 255)
        data.append(r)
        data.append(g)
        data.append(b)        
        data += write_byte(mode) #padding
        
        if is_quad:
            vmul = 4
        else:
            vmul = 3

        if is_quad:
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tvi_pos)    

            tvi_pos = vit_table[n_index*vmul+3]    
            data += write_short(tvi_pos)    

            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tvi_pos)    

            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tvi_pos)    
        else:
            tvi_pos = vit_table[n_index*vmul+0]    
            data += write_short(tvi_pos)    

            tvi_pos = vit_table[n_index*vmul+2]    
            data += write_short(tvi_pos)    

            tvi_pos = vit_table[n_index*vmul+1]    
            data += write_short(tvi_pos)    

            data += b"\x00\x00" #pad


def write_tmd_primitive(data, mesh, nit_table, vit_table, n_index, mode, flag):
        modebits = ModeBitFlags(mode)
        is_quad = modebits.is_quad
        flagmode = (mode + (flag << 8))

        packet_classes = {
            0x0020: Write_FFPacket,
            0x0030: Write_GFPacket,
            0x0024: Write_FTPacket,
            0x0121: Write_NFPacket,
            0x0034: Write_GTPacket,
            0x0036: Write_GTPacket
        }

        if flagmode in packet_classes:
            packet_classes[flagmode](data, mesh, nit_table, vit_table, n_index, is_quad, mode)




def write_tmd_file(filename):
    temp_buf = bytearray()
    vert_buf = bytearray()
    vert_off = []
    vert_cnt = []
    tvert_cnt = 0
    norm_buf = bytearray()
    norm_off = []
    norm_cnt = []
    tnorm_cnt = 0
    prim_buf = bytearray()
    prim_off = []
    prim_cnt = []
    tprim_cnt = 0
    file_buf = bytearray()


    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    sorted_objects = sorted(objects, key=lambda obj: int(obj.name))

    #do magic here
    #FILE HEADER
    temp_buf += b"\x41\x00\x00\x00"
    temp_buf += b"\x00\x00\x00\x00"

    mesh_count = 0

    for obj in sorted_objects:
        if obj.type == 'MESH':
            mesh_count += 1

    temp_buf += write_int(mesh_count)

    offsetnow = len(temp_buf)

    # Deselect all objects first
    bpy.ops.object.select_all(action='DESELECT')        

    #OBJECTS
    #VERTS
    for obj in sorted_objects:
        obj.select_set(True)  # Select the object
        bpy.context.view_layer.objects.active = obj

        # Ensure we are in Object Mode
        if bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

	    # Apply all transformations to the object
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        if obj.type == 'MESH':
            mesh = obj.data

            #ensure split normals
            mesh.calc_normals_split()

            currentv_offset = len(vert_buf)
            vert_off.append(currentv_offset)        
            currentn_offset = len(norm_buf)
            norm_off.append(currentn_offset)
            
            for vertex in mesh.vertices:
                x, y, z = vertex.co

                x_int16 = int(x)
                y_int16 = int(y)
                z_int16 = int(z)

                x_int16 = max(-32768, min(32767, x_int16))
                y_int16 = max(-32768, min(32767, y_int16))
                z_int16 = max(-32768, min(32767, z_int16))

                vert_buf.extend(struct.pack('<h', x_int16))
                vert_buf.extend(struct.pack('<h', y_int16))
                vert_buf.extend(struct.pack('<h', z_int16))
                vert_buf += b'\x00\x00'  # 2 bytes of filler

                tvert_cnt += 1                

            #Normals

            unique_normals = []
            unique_normalst = {}
            vit_table = []
            vit_table_set = {}
            nit_table = []
            nitnor_table = []
            tolerance = 4
            custom_order = [0, 2, 1]

            for face in mesh.polygons:
                loop_indices = face.loop_indices
                for i in range(0, len(loop_indices), 3):
                    group = [loop_indices[i], loop_indices[i + 1], loop_indices[i + 2]]
                    reordered_group = [group[j] for j in custom_order]


                for loop_index in reordered_group: 
                    
                    
                    loop = mesh.loops[loop_index]
                    lonorm = loop.normal 
                    x, y, z = packNormal(lonorm)                
                    tx = truncate_float(loop.normal[0],4)
                    ty = truncate_float(loop.normal[1],4)
                    tz = truncate_float(loop.normal[2],4)
                    ltnorm = (x, y, z)
                    vertid = loop.vertex_index
                    is_unique = True

                    #Add to tables
                    vit_table.append(vertid) #Store loop.vertex_index just for giggles
                    nitnor_table.append(ltnorm) #Store truncated normal

                    #if normal appeared before
                    if vertid in vit_table_set:
                        is_unique = False
                        nit_ind = vit_table_set[vertid]
                    else:    
                        for ux, uy, uz in unique_normalst:
                            if (abs(x - ux) < tolerance and
                                abs(y - uy) < tolerance and
                                abs(z - uz) < tolerance) :
                                is_unique = False
                                nit_ind = unique_normalst[(ux, uy, uz)]
                                break    


                    if is_unique:                                 
                        nit_ind = len(unique_normals)
                        unique_normalst[ltnorm] = nit_ind #Store position inside the unique normals table
                        vit_table_set[vertid] = nit_ind
                        unique_normals.append((x, y, z))  # Append actual normal to list of unique normals               
                                                

                    nit_table.append(nit_ind)    


            for normal in unique_normals:                
                norm_buf += write_normal(normal)
                tnorm_cnt += 1
            
            vert_cnt.append(tvert_cnt)
            tvert_cnt = 0
            norm_cnt.append(tnorm_cnt)
            tnorm_cnt = 0

        
        #PRIMITIVES    
        mesh = obj.data
        current_offset = len(prim_buf)
        prim_off.append(current_offset)
        bm = bmesh.new()            
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
            
        modeflag = bm.faces.layers.int.get("FaceModeFlags")
        flagflag = bm.faces.layers.int.get("FaceFlagFlags")

        for n_index, face in enumerate(bm.faces):
            face_index = face.index

            flag = bm.faces[face.index][flagflag]                
            mode = bm.faces[face.index][modeflag]                

            if (mode & 0x3F) == 0x20:  # 0x20 and 0x21
                ilen = 0x3 + ((flag & 0x04) >> 2) * 0x2
                olen = 0x4 + ((flag & 0x04) >> 2) * 0x2
            elif (mode & 0x3F) == 0x24:  # 0x24 and 0x25
                ilen = 0x5
                olen = 0x7
            elif (mode & 0x3F) == 0x30:  # 0x30 and 0x31
                ilen = 0x4 + ((flag & 0x04) >> 2) * 0x2 + ((flag & 0x01) << 0x1)
                olen = 0x6
            elif (mode & 0x3F) == 0x34:  # 0x34 and 0x35
                ilen = 0x6 + ((flag & 0x01) << 0x1)
                olen = 0x9

            prim_buf.extend(olen.to_bytes(1, byteorder='little'))
            prim_buf.extend(ilen.to_bytes(1, byteorder='little'))

            prim_buf += write_byte(flag)                
            prim_buf += write_byte(mode)

            #Write primitives data
            write_tmd_primitive(prim_buf, bm, nit_table, vit_table, n_index, mode, flag)

            tprim_cnt += 1
                
        prim_cnt.append(tprim_cnt)
        tprim_cnt = 0 

    vertlen = len(vert_buf)
    normlen = len(norm_buf)
    primlen = len(prim_buf)

    offsetnow = mesh_count * 28

    
    for i in range(mesh_count):
        vt = vert_off[i] + primlen + offsetnow
        temp_buf += write_int(vt)
        vtcnt = vert_cnt[i] 
        temp_buf += write_int(vtcnt)

        nt = norm_off[i] + primlen + vertlen + offsetnow
        temp_buf += write_int(nt)
        ntcnt = norm_cnt[i] 
        temp_buf += write_int(ntcnt)

        pt = prim_off[i] + offsetnow
        temp_buf += write_int(pt)
        ptcnt = prim_cnt[i] 
        temp_buf += write_int(ptcnt)

        temp_buf.extend(b'\x00' * 4) #Pad

        print("OUTPUT MODEL")

        print(f"vertAddress: 0x{vt:x}")
        print(f"normalAddress: 0x{nt:x}")
        print(f"primitiveAddress: 0x{pt:x}")
    
    temp_buf += prim_buf
    temp_buf += vert_buf
    temp_buf += norm_buf
    

    file_buf += temp_buf
    temp_buf = ""

    file = open(filename,'wb')
    file.write(file_buf)
    file.close()
    



def tmd_save(context, filepath):

    if not filepath:
        raise ValueError("Filepath is not provided")

    fname = os.path.basename(filepath)

    if filepath != "":
        if not filepath.endswith(".tmd"):
            filepath += ".tmd"

        obj_list = []
        obj_list = bpy.data.objects

        if len(obj_list) > 0:
            write_tmd_file(filepath)



# Operator definition
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper
from bpy.types import Operator

class ImportTMD(Operator, ImportHelper):
    bl_idname = "import_scene.tmd"
    bl_label = "Import TMD"
    filename_ext = ".tmd"

    def execute(self, context):
        filepath = self.filepath
        read_tmd(context, filepath)
        
        return {'FINISHED'}

class ExportTMD(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.tmd"
    bl_label = 'Export TMD'
    filename_ext = ".tmd"

    def execute(self, context):
        filepath = self.filepath
        tmd_save(context, filepath)
        return {'FINISHED'}

def RegisterFaceData():
    scene = bpy.context.scene
    
    if bpy.context.object and bpy.context.object.mode == 'EDIT' and bpy.context.tool_settings.mesh_select_mode[2]:
        selected_faces = [p.index for p in bpy.context.object.data.polygons if p.select]

        bpy.ops.object.mode_set(mode='OBJECT')
        mesh = bpy.context.object.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        
        if selected_faces:            
            active_face = selected_faces[0]
            for attr_name in ["FaceModeFlags", "FaceFlagFlags", "Clut", "TXB"]:
                attrdata = mesh.attributes.get(attr_name)
                if attrdata:
                    # Access attribute data
                    flags_encoded = attrdata.data[active_face].value
                
                    if attr_name == "FaceModeFlags":
                        flags = ModeBitFlags(flags_encoded)
                        scene.toggle_brightness = flags.is_brightness
                        scene.toggle_transparency = flags.is_transparency
                        scene.toggle_texture = flags.is_texture
                        scene.toggle_quad = flags.is_quad
                        scene.toggle_gouraud = flags.is_gouraud
                    elif attr_name == "FaceFlagFlags":
                        flags = FlagBitFlags(flags_encoded)
                        scene.toggle_lights = flags.is_light_source
                        scene.toggle_twosided = flags.is_two_sided
                        scene.toggle_gradation = flags.is_gradation
                    elif attr_name == "Clut":
                        cba = attrdata.data[active_face].value
                        clut = ClutCoordinates(cba)
                        scene.ClutX = clut.clut_x
                        scene.ClutY = clut.clut_y
                    elif attr_name == "TXB":
                        txb_d = attrdata.data[active_face].value
                        txb = TexturePageAttributes(txb_d)
                        scene.TexPage = txb.texture_page
                        scene.Semitran = txb.semitransparency_rate
                        scene.TXBCM = txb.colour_mode

        bpy.ops.object.mode_set(mode='EDIT')
    return 0.1

def toggle_ModFlags_update(self, context):
    obj = bpy.context.object
    mesh = obj.data if obj else None  # Access mesh data if object exists, otherwise None
    scene = bpy.context.scene if bpy.context.scene else None  # Access scene if it exists, otherwise None
    
    if obj and mesh and scene:

        encoded_flags = (
            int(scene.toggle_brightness) |
            (int(scene.toggle_transparency) << 1) |
            (int(scene.toggle_texture) << 2) |
            (int(scene.toggle_quad) << 3) |
            (int(scene.toggle_gouraud) << 4) |
            (int(1) << 5)
        )
    
        bm = bmesh.from_edit_mesh(context.object.data)
        selected_faces = [f for f in bm.faces if f.select]
        
        face_flags_layer = bm.faces.layers.int["FaceModeFlags"] 
        if face_flags_layer:
            selected_faces = [f for f in bm.faces if f.select]
            for face in selected_faces:
                face[face_flags_layer] = encoded_flags
            
        bmesh.update_edit_mesh(mesh)
        bm.free()    
    
def toggle_FlagFlags_update(self, context):
    obj = bpy.context.object
    mesh = obj.data if obj else None  # Access mesh data if object exists, otherwise None
    scene = bpy.context.scene if bpy.context.scene else None  # Access scene if it exists, otherwise None

    if obj and mesh and scene:
        encoded_flags = (    
        int(scene.toggle_lights) |
            (int(scene.toggle_twosided) << 1) |
            (int(scene.toggle_gradation) << 2)
        )    

        bm = bmesh.from_edit_mesh(context.object.data)
        selected_faces = [f for f in bm.faces if f.select]
        
        face_flags_layer = bm.faces.layers.int["FaceFlagFlags"] 
        if face_flags_layer:
            selected_faces = [f for f in bm.faces if f.select]
            for face in selected_faces:
                face[face_flags_layer] = encoded_flags
            
        bmesh.update_edit_mesh(mesh)
        bm.free()    

def toggle_NumericClut_update(self, context):
    obj = bpy.context.object
    mesh = obj.data if obj else None  # Access mesh data if object exists, otherwise None
    scene = bpy.context.scene if bpy.context.scene else None  # Access scene if it exists, otherwise None

    if obj and mesh and scene:
        encoded_clut = (scene.ClutX // 16) + (scene.ClutY * 64)
	
        bm = bmesh.from_edit_mesh(context.object.data)
        selected_faces = [f for f in bm.faces if f.select]
        
        face_flags_layer = bm.faces.layers.int["Clut"] 
        if face_flags_layer:
            selected_faces = [f for f in bm.faces if f.select]
            for face in selected_faces:
                face[face_flags_layer] = encoded_clut
            
        bmesh.update_edit_mesh(mesh)
        bm.free()    

def toggle_NumericFlag_update(self, context):
    obj = bpy.context.object
    mesh = obj.data if obj else None  # Access mesh data if object exists, otherwise None
    scene = bpy.context.scene if bpy.context.scene else None  # Access scene if it exists, otherwise None

    if obj and mesh and scene:
        encoded_flags = (scene.TXBCM << 7) | (scene.Semitran << 5) | scene.TexPage   

        bm = bmesh.from_edit_mesh(context.object.data)
        selected_faces = [f for f in bm.faces if f.select]
        
        face_flags_layer = bm.faces.layers.int["TXB"] 
        if face_flags_layer:
            selected_faces = [f for f in bm.faces if f.select]
            for face in selected_faces:
                face[face_flags_layer] = encoded_flags
            
        bmesh.update_edit_mesh(mesh)
        bm.free()    

def CreateFlagsFunc():
    obj = bpy.context.object
    mesh = obj.data if obj else None

    attr_name = "FaceModeFlags"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    # Access the attribute data
    face_data_attr = mesh.attributes[attr_name].data

    for i in range(len(face_data_attr)):
        face_data_attr[i].value = 0
    #------------------------------
    attr_name = "FaceFlagFlags"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    # Access the attribute data
    face_data_attr = mesh.attributes[attr_name].data

    for i in range(len(face_data_attr)):
        face_data_attr[i].value = 0
    #------------------------------
    attr_name = "Clut"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    # Access the attribute data
    face_data_attr = mesh.attributes[attr_name].data

    for i in range(len(face_data_attr)):
        face_data_attr[i].value = 0
    #------------------------------
    attr_name = "TXB"  # Name of the attribute
    if not mesh.attributes.get(attr_name):
        face_data_attr = mesh.attributes.new(name=attr_name, type='INT', domain='FACE')

    # Access the attribute data
    face_data_attr = mesh.attributes[attr_name].data

    for i in range(len(face_data_attr)):
        face_data_attr[i].value = 0
    
    
    # Ensure mesh update
    mesh.update()

class CreateFlags(bpy.types.Operator):
    bl_idname = "object.addflags_operator"
    bl_description = "Create flag fields for selected faces assuming textured"
    bl_label = "CreateFlags"
    
    def execute(self, context):
        CreateFlagsFunc()
        return {'FINISHED'}

class MESH_PT_mode_bit_flags(bpy.types.Panel):
    bl_label = "TMD Data"
    bl_idname = "MESH_PT_mode_bit_flags"
    bl_space_type = 'PROPERTIES'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'    
    bl_category = 'TMD Data'

    @classmethod
    def poll(cls, context):
        return (context.mode == 'EDIT_MESH' and
                context.tool_settings.mesh_select_mode[2])

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        obj = bpy.context.edit_object
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)

        if not mesh.attributes.get("FaceModeFlags"):
            layout.operator("object.addflags_operator")
            return

        box1 = layout.box()
        box1.prop(context.scene, "dropdown_1", text="Mode Bit Flags", icon='TRIA_DOWN' if context.scene.dropdown_1 else 'TRIA_RIGHT')                    
        box2 = layout.box()
        box2.prop(context.scene, "dropdown_2", text="Flag Bit Flags", icon='TRIA_DOWN' if context.scene.dropdown_2 else 'TRIA_RIGHT')                    
        box3 = layout.box()
        box3.prop(context.scene, "dropdown_3", text="Clut", icon='TRIA_DOWN' if context.scene.dropdown_3 else 'TRIA_RIGHT')                    
        box4 = layout.box()
        box4.prop(context.scene, "dropdown_4", text="TexPage Attributes", icon='TRIA_DOWN' if context.scene.dropdown_4 else 'TRIA_RIGHT')                    
        selfaces = []
        for f in bm.faces:
            if f.select:
                selfaces.append(f.index)
        bm.free()



        if selfaces:
            #get attr
            if mesh.attributes.get("FaceModeFlags"):
                if len(selfaces) == 1:
                    col.label(text=f"Face Index: {selfaces[0]}")
                else:    
                    col.label(text=f"Multiple Faces.")
    
                if context.scene.dropdown_1:
                    
                    # Add a row with three on/off buttons
                    row = box1.row()
                    row.prop(context.scene, "toggle_brightness", text="Brightness", toggle = True)
                    row.prop(context.scene, "toggle_transparency", text="Transparency", toggle = True)
                    row.prop(context.scene, "toggle_texture", text="Texture", toggle = True)
                    
                    row = box1.row()
                    row.prop(context.scene, "toggle_quad", text="Quad", toggle = True)
                    row.prop(context.scene, "toggle_gouraud", text="Gouraud", toggle = True)

                    row = box1.row()
                    row.enabled = False 
                    row.prop(context.scene, "toggle_bit_5", text="Bit 5", toggle = True)
            #get attr
            if mesh.attributes.get("FaceFlagFlags"):
                if context.scene.dropdown_2:
                    # Add a row with three on/off buttons
                    row = box2.row()
                    row.prop(context.scene, "toggle_lights", text="Light Source", toggle = True)
                    row.prop(context.scene, "toggle_twosided", text="TwoSided", toggle = True)
                    row.prop(context.scene, "toggle_gradation", text="Gradation", toggle = True)

            #get attr
            if mesh.attributes.get("Clut"):
                if context.scene.dropdown_3:
                    row = box3.row()
                    box3.prop(context.scene, "ClutX")                
                    box3.prop(context.scene, "ClutY")                
            #get attr
            if mesh.attributes.get("TXB"):
                if context.scene.dropdown_4:
                    row = box4.row()
                    box4.prop(context.scene, "TexPage")                
                    box4.prop(context.scene, "Semitran")                
                    box4.prop(context.scene, "TXBCM")                
                
        else:
            col.label(text="No faces selected.")


def menu_func_export(self, context):
    self.layout.operator(ExportTMD.bl_idname, text="TMD (.tmd)")

def menu_func_import(self, context):
    self.layout.operator(ImportTMD.bl_idname, text="TMD (.tmd)")


def register():
    bpy.utils.register_class(ImportTMD)
    bpy.utils.register_class(ExportTMD)
    bpy.utils.register_class(CreateFlags)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.utils.register_class(MESH_PT_mode_bit_flags)  # Register custom panel class
    bpy.app.timers.register(RegisterFaceData)
    bpy.types.Scene.toggle_brightness = bpy.props.BoolProperty(name="Toggle Brightness", update=toggle_ModFlags_update)
    bpy.types.Scene.toggle_transparency = bpy.props.BoolProperty(name="Toggle Transparency", update=toggle_ModFlags_update)
    bpy.types.Scene.toggle_texture = bpy.props.BoolProperty(name="Toggle Is Texture", update=toggle_ModFlags_update)
    bpy.types.Scene.toggle_quad = bpy.props.BoolProperty(name="Toggle Quad", update=toggle_ModFlags_update)
    bpy.types.Scene.toggle_gouraud = bpy.props.BoolProperty(name="Toggle Gouraud", update=toggle_ModFlags_update)
    bpy.types.Scene.toggle_bit_5 = bpy.props.BoolProperty(name="Toggle Bit 5")
    bpy.types.Scene.dropdown_1 = bpy.props.BoolProperty(name="Drop 1")
    bpy.types.Scene.dropdown_2 = bpy.props.BoolProperty(name="Drop 2")
    bpy.types.Scene.dropdown_3 = bpy.props.BoolProperty(name="Drop 3")    
    bpy.types.Scene.dropdown_4 = bpy.props.BoolProperty(name="Drop 4")    
    bpy.types.Scene.toggle_lights = bpy.props.BoolProperty(name="Toggle Lights", update=toggle_FlagFlags_update)
    bpy.types.Scene.toggle_twosided = bpy.props.BoolProperty(name="Toggle Twosided", update=toggle_FlagFlags_update)
    bpy.types.Scene.toggle_gradation = bpy.props.BoolProperty(name="Toggle Gradatopm", update=toggle_FlagFlags_update)
    bpy.types.Scene.ClutX = bpy.props.IntProperty(name="ClutX", description="Enter a numeric value", default=0, min=0, max=1024, update=toggle_NumericClut_update)
    bpy.types.Scene.ClutY = bpy.props.IntProperty(name="ClutY", description="Enter a numeric value", default=0, min=0, max=1024, update=toggle_NumericClut_update)
    bpy.types.Scene.TexPage = bpy.props.IntProperty(name="TexPage", description="Enter a numeric value", default=0, min=0, max=100, update=toggle_NumericFlag_update)
    bpy.types.Scene.Semitran = bpy.props.IntProperty(name="Semitransparency", description="Enter a numeric value", default=0, min=0, max=3, update=toggle_NumericFlag_update)
    bpy.types.Scene.TXBCM = bpy.props.IntProperty(name="Color Mode", description="Enter a numeric value", default=0, min=0, max=2, update=toggle_NumericFlag_update)

def unregister():
    bpy.utils.unregister_class(ImportTMD)
    bpy.utils.unregister_class(ExportTMD)
    bpy.utils.unregister_class(CreateFlags)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.utils.unregister_class(MESH_PT_mode_bit_flags)  # Unregister custom panel class
    bpy.app.timers.unregister(RegisterFaceData)
    del bpy.types.Scene.toggle_brightness
    del bpy.types.Scene.toggle_transparency
    del bpy.types.Scene.toggle_texture
    del bpy.types.Scene.toggle_quad
    del bpy.types.Scene.toggle_gouraud
    del bpy.types.Scene.toggle_bit_5
    del bpy.types.Scene.dropdown_1
    del bpy.types.Scene.dropdown_2
    del bpy.types.Scene.dropdown_3
    del bpy.types.Scene.dropdown_4
    del bpy.types.Scene.toggle_lights
    del bpy.types.Scene.toggle_twosided
    del bpy.types.Scene.toggle_gradation    
    del bpy.types.Scene.ClutX
    del bpy.types.Scene.ClutY
    del bpy.types.Scene.TexPage
    del bpy.types.Scene.Semitran
    del bpy.types.Scene.TXBCM
    
# This allows you to run the script directly from Blender's text editor to test the addon.
if __name__ == "__main__":
    register()
