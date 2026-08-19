import re
import sys

release_version = sys.argv[1]

print(f"release version is {release_version}")

if not release_version.startswith("v"):
    print('release version must start with "v" to publish')
    sys.exit(1)

if re.search("[a-zA-Z]", release_version.split("v")[1]):
    print("release version must not have alpha suffix")
    sys.exit(2)

if "-" in release_version:
    print("release version must not have a dash")
    sys.exit(3)

print("release version format is valid")
