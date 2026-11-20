"""Writes installer/version_info.txt so Jarvis.exe carries a real version
and publisher in its file properties (Windows and antivirus both read it).
Usage: python installer/make_version_info.py 1.09"""
import os
import sys

ver = sys.argv[1] if len(sys.argv) > 1 else "0.0"
parts = [int(p) for p in ver.split(".") if p.isdigit()][:4]
parts += [0] * (4 - len(parts))
tup = tuple(parts)

text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'VanshCoder01'),
      StringStruct('FileDescription', 'J.A.R.V.I.S voice assistant'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'Jarvis'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'Jarvis.exe'),
      StringStruct('ProductName', 'J.A.R.V.I.S'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_info.txt")
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(f"[OK] version info {ver}")
