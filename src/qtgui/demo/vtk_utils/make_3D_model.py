#!/usr/bin/env python3
"""Generate 3D demo models: bracket | blob | terrain | gear"""

import sys
import struct
import math
import os

# ───────────────────────────── STL writer (binary) ─────────────────────────────
def write_stl_binary(triangles, filename):
    """Write a binary STL file from a list of triangles."""
    header = b"Binary STL " + b"\x00" * 70       # 80‑byte header
    with open(filename, "wb") as f:
        f.write(header[:80])
        f.write(struct.pack("<I", len(triangles)))
        for tri in triangles:
            v0, v1, v2 = tri
            ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
            bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
            nx = ay * bz - az * by
            ny = az * bx - ax * bz
            nz = ax * by - ay * bx
            mag = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
            f.write(struct.pack("<fff", nx/mag, ny/mag, nz/mag))
            for v in (v0, v1, v2):
                f.write(struct.pack("<fff", *v))
            f.write(b"\x00\x00")   # attribute byte count
    # Self‑check: file size should be 84 + len(triangles)*50
    expected = 84 + len(triangles) * 50
    actual = os.path.getsize(filename)
    assert actual == expected, f"STL file size mismatch: expected {expected}, got {actual}"

# ──────────────── Model 1: L‑bracket ─────────────────────────────────
def make_bracket(filename="mechanical_bracket.stl"):
    tris = []
    def box(x0,x1,y0,y1,z0,z1):
        return [
            *quad((x0,y0,z0),(x0,y0,z1),(x0,y1,z1),(x0,y1,z0)),
            *quad((x1,y0,z0),(x1,y1,z0),(x1,y1,z1),(x1,y0,z1)),
            *quad((x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)),
            *quad((x0,y1,z0),(x0,y1,z1),(x1,y1,z1),(x1,y1,z0)),
            *quad((x0,y0,z0),(x0,y1,z0),(x1,y1,z0),(x1,y0,z0)),
            *quad((x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)),
        ]
    tris += box(0,8,0,1.5,0,0.6)
    tris += box(0,1.5,0,1.5,0,5)
    tris += box(0,1.5,0,1.5,0.55,0.65)
    N=40; cx,cy,cz,r,h=5.0,0.75,0.6,0.5,0.5
    for i in range(N):
        a0=2*math.pi*i/N; a1=2*math.pi*(i+1)/N
        p0=(cx+r*math.cos(a0),cy+r*math.sin(a0),cz)
        p1=(cx+r*math.cos(a1),cy+r*math.sin(a1),cz)
        p2=(cx+r*math.cos(a0),cy+r*math.sin(a0),cz+h)
        p3=(cx+r*math.cos(a1),cy+r*math.sin(a1),cz+h)
        bot=(cx,cy,cz); top=(cx,cy,cz+h)
        tris.append((bot,p1,p0))
        tris.append((top,p2,p3))
        tris.append((p0,p1,p3))
        tris.append((p0,p3,p2))
    write_stl_binary(tris, filename)
    print(f"✔ {filename}  ({len(tris)} triangles)")
    return filename

def quad(a,b,c,d):
    return [(a,b,c),(a,c,d)]

# ──────────────── Model 2: Organic blob (PLY) ─────────────────────────
def make_organic_blob(filename="organic_blob.ply"):
    lat_steps=lon_steps=64
    verts=[]
    faces=[]
    def noise(x,y,z):
        return (0.18*math.sin(3*x)*math.cos(2*y)+0.12*math.sin(5*y)*math.sin(4*z)+0.08*math.cos(7*x+3*z))
    for i in range(lat_steps+1):
        theta=math.pi*i/lat_steps
        for j in range(lon_steps):
            phi=2*math.pi*j/lon_steps
            x=math.sin(theta)*math.cos(phi); y=math.sin(theta)*math.sin(phi); z=math.cos(theta)
            r=1.0+noise(x,y,z)
            verts.append((r*x,r*y,r*z))
    for i in range(lat_steps):
        for j in range(lon_steps):
            a=i*lon_steps+j; b=i*lon_steps+(j+1)%lon_steps
            c=(i+1)*lon_steps+j; d=(i+1)*lon_steps+(j+1)%lon_steps
            faces.append((a,b,d,c))
    with open(filename,"w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {len(verts)}\nproperty float x\nproperty float y\nproperty float z\n")
        f.write(f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n")
        for v in verts: f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces: f.write(f"4 {face[0]} {face[1]} {face[2]} {face[3]}\n")
    print(f"✔ {filename} ({len(verts)} verts, {len(faces)} faces)")
    return filename

# ──────────────── Model 3: Terrain (VTK) ──────────────────────────────
def make_terrain(filename="terrain_patch.vtk"):
    nx=ny=80; sx=sy=10.0; pts=[]
    def height(u,v):
        return (0.6*math.sin(2*u)*math.cos(2*v)+0.3*math.sin(5*u+1)*math.sin(3*v)+0.15*math.cos(7*u)*math.sin(6*v))
    for j in range(ny):
        for i in range(nx):
            u=math.pi*i/(nx-1); v=math.pi*j/(ny-1)
            x=sx*i/(nx-1); y=sy*j/(ny-1); z=height(u,v)
            pts.append((x,y,z))
    faces=[]
    for j in range(ny-1):
        for i in range(nx-1):
            a=j*nx+i; b=j*nx+(i+1); c=(j+1)*nx+(i+1); d=(j+1)*nx+i
            faces.append((a,b,c,d))
    with open(filename,"w") as f:
        f.write("# vtk DataFile Version 3.0\nTerrain patch\nASCII\n")
        f.write("DATASET POLYDATA\n")
        f.write(f"POINTS {len(pts)} float\n")
        for p in pts: f.write(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
        f.write(f"\nPOLYGONS {len(faces)} {5*len(faces)}\n")
        for face in faces: f.write(f"4 {face[0]} {face[1]} {face[2]} {face[3]}\n")
    print(f"✔ {filename} ({len(pts)} pts, {len(faces)} quads)")
    return filename

# ──────────────── Model 4: Spur gear ( guaranteed outward normals ) ───
def make_gear(filename="spur_gear.stl", teeth=16, pitch_radius=2.0, tooth_height=0.4,
              thickness=0.5, hole_radius=0.5, angular_resolution=120):
    outer_r = pitch_radius + tooth_height/2
    inner_r = pitch_radius - tooth_height/2
    half = thickness/2
    center = (0.0, 0.0, 0.0)

    # Profile points
    total_steps = teeth * angular_resolution
    prof_top, prof_bot = [], []
    hole_top, hole_bot = [], []
    for step in range(total_steps):
        ang = 2 * math.pi * step / total_steps
        frac = (step % angular_resolution) / angular_resolution
        r = outer_r if frac < 0.5 else inner_r
        x, y = r * math.cos(ang), r * math.sin(ang)
        prof_top.append((x, y, half))
        prof_bot.append((x, y, -half))
        xh, yh = hole_radius * math.cos(ang), hole_radius * math.sin(ang)
        hole_top.append((xh, yh, half))
        hole_bot.append((xh, yh, -half))

    tris = []
    def add_tri(v0, v1, v2):
        """Add triangle with forced outward normal (away from center)."""
        ax, ay, az = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
        bx, by, bz = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
        nx = ay*bz - az*by
        ny = az*bx - ax*bz
        nz = ax*by - ay*bx
        # centroid
        cx = (v0[0]+v1[0]+v2[0]) / 3.0
        cy = (v0[1]+v1[1]+v2[1]) / 3.0
        cz = (v0[2]+v1[2]+v2[2]) / 3.0
        dot = nx*(center[0]-cx) + ny*(center[1]-cy) + nz*(center[2]-cz)
        if dot < 0:
            tris.append((v0, v2, v1))
        else:
            tris.append((v0, v1, v2))

    def add_quad(a,b,c,d):
        add_tri(a, b, c)
        add_tri(a, c, d)

    n = len(prof_top)
    for i in range(n):
        j = (i+1) % n
        add_quad(prof_bot[i], prof_bot[j], prof_top[j], prof_top[i])   # outer wall
        add_quad(hole_bot[j], hole_bot[i], hole_top[i], hole_top[j])   # inner wall
        add_quad(prof_top[i], prof_top[j], hole_top[j], hole_top[i])   # top cap
        add_quad(hole_bot[i], hole_bot[j], prof_bot[j], prof_bot[i])   # bottom cap

    write_stl_binary(tris, filename)
    print(f"✔ {filename} ({len(tris)} triangles)")
    return filename

# ──────────────────────────── Main ────────────────────────────────
MODELS = {
    "bracket": (make_bracket, "mechanical_bracket.stl"),
    "blob": (make_organic_blob, "organic_blob.ply"),
    "terrain": (make_terrain, "terrain_patch.vtk"),
    "gear": (make_gear, "spur_gear.stl"),
}

if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "bracket"
    if choice not in MODELS:
        print(f"Unknown model '{choice}'. Choose from: {', '.join(MODELS)}")
        sys.exit(1)

    fn, default_out = MODELS[choice]
    try:
        generated = fn(default_out)
        print(f"\nGenerated '{generated}'")
    except Exception as e:
        print(f"\nERROR generating {choice}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)