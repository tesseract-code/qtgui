import struct
import sys


def inspect_stl(filepath):
    with open(filepath, "rb") as f:
        header = f.read(80)
        if len(header) < 80:
            print("File too short for a valid STL header.")
            return
        count_bytes = f.read(4)
        if len(count_bytes) < 4:
            print("Missing triangle count.")
            return
        n_tri = struct.unpack("<I", count_bytes)[0]
        print(f"Header claims {n_tri} triangles.")

        xmin = ymin = zmin = 1e9
        xmax = ymax = zmax = -1e9
        bad_normals = 0
        actual_tris = 0

        while True:
            chunk = f.read(50)  # 12 floats (48) + 2 bytes attribute
            if not chunk:
                break
            if len(chunk) < 50:
                print(
                    f"Warning: Incomplete triangle at byte {f.tell() - len(chunk)} (expected 50, got {len(chunk)})")
                break
            floats = struct.unpack("<12f", chunk[:48])
            nx, ny, nz = floats[:3]
            # Check zero normal
            if abs(nx) < 1e-9 and abs(ny) < 1e-9 and abs(nz) < 1e-9:
                bad_normals += 1
            # Update bounding box from vertices (indices 3..11)
            for k in range(3, 12, 3):
                x, y, z = floats[k], floats[k + 1], floats[k + 2]
                if x < xmin: xmin = x
                if y < ymin: ymin = y
                if z < zmin: zmin = z
                if x > xmax: xmax = x
                if y > ymax: ymax = y
                if z > zmax: zmax = z
            actual_tris += 1

        print(f"Actually read: {actual_tris} triangles")
        if actual_tris:
            print(
                f"Bounding box: ({xmin:.3f}, {ymin:.3f}, {zmin:.3f}) - ({xmax:.3f}, {ymax:.3f}, {zmax:.3f})")
            print(f"Zero (degenerate) normals: {bad_normals}")
        else:
            print("No triangle data found.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_stl.py filename.stl")
    else:
        inspect_stl(sys.argv[1])