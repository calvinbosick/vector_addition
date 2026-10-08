
import math

AxMagStr = input("Enter the magnitude of the first vector:\n")
AxAngleStr = input("Enter the angle of the first vector:\n")
BxMagStr = input("Enter the magnitude of the second vector:\n")
BxAngleStr = input("Enter the angle of the second vector:\n")

# Convert the input values to numbers
AxAngleDeg = int(AxAngleStr)
BxAngleDeg = int(BxAngleStr)
AxMag = int(AxMagStr)
BxMag = int(BxMagStr)

# Convert angles from degrees to radians
# Python's sin() and cos() functions use radians
AxAngleRad = math.radians(AxAngleDeg)
BxAngleRad = math.radians(BxAngleDeg)

# Find the x and y components of the first vector
AxAngleCos = math.cos(AxAngleRad)
Ax = AxAngleCos * AxMag

AxAngleSin = math.sin(AxAngleRad)
Ay = AxAngleSin * AxMag

# Find the x and y components of the second vector
BxAngleCos = math.cos(BxAngleRad)
Bx = BxAngleCos * BxMag

BxAngleSin = math.sin(BxAngleRad)
By = BxAngleSin * BxMag

# Add the x components and y components
Cx = Ax + Bx
Cy = Ay + By

# Square the x and y components
Cxx = Cx * Cx
Cyy = Cy * Cy

# Add the squared components
Cxy = Cxx + Cyy

# Find the magnitude of the resultant vector
finalMag = math.sqrt(Cxy)

# Find the direction of the resultant vector
# atan2() automatically handles the correct quadrant
finalAngle = math.degrees(math.atan2(Cy, Cx))

# Convert negative angles into the 0-360 degree range
if finalAngle < 0:
    finalAngle += 360

print(f"Cx = {Cx}")
print(f"Cy = {Cy}")
print(f"Magnitude = {finalMag}")
print(f"Direction = {finalAngle} degrees")
