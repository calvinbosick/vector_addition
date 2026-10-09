import math


def read_number(prompt):
    """Keep asking until the user enters a valid number."""
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Please enter a valid number (for example, 12 or 12.5).")


def main():
    print("Vector Addition")
    print("Angles are measured counterclockwise from the positive x-axis.")
    print("Intermediate values are kept at full floating-point precision.\n")

    try:
        ax_mag = read_number("Enter the magnitude of the first vector: ")
        ax_angle_deg = read_number("Enter the angle of the first vector (degrees): ")
        bx_mag = read_number("Enter the magnitude of the second vector: ")
        bx_angle_deg = read_number("Enter the angle of the second vector (degrees): ")
    except (KeyboardInterrupt, EOFError):
        print("\nExiting vector addition.")
        return

    # Keep full-precision floating-point results for every intermediate step.
    ax_angle = math.radians(ax_angle_deg)
    bx_angle = math.radians(bx_angle_deg)

    ax = ax_mag * math.cos(ax_angle)
    ay = ax_mag * math.sin(ax_angle)
    bx = bx_mag * math.cos(bx_angle)
    by = bx_mag * math.sin(bx_angle)

    cx = ax + bx
    cy = ay + by
    result_mag = math.hypot(cx, cy)

    # atan2 uses the unrounded components and correctly handles all quadrants.
    if cx == 0.0 and cy == 0.0:
        result_angle = None
    else:
        result_angle = math.degrees(math.atan2(cy, cx)) % 360.0
        if math.isclose(result_angle, 360.0, abs_tol=1e-10):
            result_angle = 0.0

    print("\n--- Result (rounded only for display) ---")
    print(f"First vector components: Ax = {ax:.10f}, Ay = {ay:.10f}")
    print(f"Second vector components: Bx = {bx:.10f}, By = {by:.10f}")
    print(f"Resultant x-component = {cx:.10f}")
    print(f"Resultant y-component = {cy:.10f}")
    print(f"Magnitude = {result_mag:.10f}")
    if result_angle is None:
        print("Direction = undefined (the resultant magnitude is zero)")
    else:
        print(f"Direction = {result_angle:.10f} degrees")

    try:
        input("\nPress Enter to close...")
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
