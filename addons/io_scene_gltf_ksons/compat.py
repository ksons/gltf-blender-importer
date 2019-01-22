import bpy

# Compatiblity shims

# Blender 2.8 changed matrix-matrix, matrix-vector, quaternion-quaternion, and
# quaternion-vector multiplication from x * y to x @ y
if bpy.app.version >= (2, 80, 0):
    def mul(x, y): return x @ y
else:
    def mul(x, y): return x * y
