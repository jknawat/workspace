import sys
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime


def generate_image(prompt, filename=None, width=1024, height=1024):
    print(f"\nGenerating image...")
    print(f"Prompt: {prompt}\n")

    encoded_prompt = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&model=flux&nologo=true"

    output_dir = Path(__file__).parent / "generated_images"
    output_dir.mkdir(exist_ok=True)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"image_{timestamp}.jpg"

    output_path = output_dir / filename

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            output_path.write_bytes(response.read())
        print(f"Done! Saved to: {output_path}")
        return str(output_path)
    except Exception as e:
        print(f"Error: {e}")
        return None


def menu_product_mockup():
    print("\n--- Product Mockup (for STL file listing) ---")
    product = input("What is your product? (e.g. F1 car display stand): ").strip()
    material = input("Material/color? (e.g. black matte plastic): ").strip()
    background = input("Background style? (e.g. white studio, dark dramatic): ").strip()

    prompt = (
        f"Professional product photography of a 3D printed {product}, "
        f"made of {material}, {background} background, "
        f"high quality, sharp focus, commercial product photo style, "
        f"no text, no watermark"
    )
    generate_image(prompt)


def menu_social_media():
    print("\n--- Social Media Graphic (TikTok / YouTube Thumbnail) ---")
    topic = input("What is the video about? (e.g. How I 3D printed an F1 trophy): ").strip()
    style = input("Style? (e.g. bold, colorful, dark, minimal): ").strip()
    aspect = input("Format? (1=Square 1:1, 2=YouTube 16:9, 3=TikTok 9:16): ").strip()

    width, height = 1024, 1024
    if aspect == "2":
        width, height = 1280, 720
    elif aspect == "3":
        width, height = 720, 1280

    prompt = (
        f"YouTube thumbnail or TikTok cover for a video about '{topic}', "
        f"{style} style, eye-catching, bold design, "
        f"high contrast, professional content creator design, no text"
    )
    generate_image(prompt, width=width, height=height)


def menu_shopee_listing():
    print("\n--- Shopee / Lazada Product Image ---")
    product = input("Product name: ").strip()
    color = input("Product color: ").strip()
    usp = input("Main selling point? (e.g. cute design, sturdy, unique): ").strip()

    prompt = (
        f"E-commerce product photo of {product} in {color}, "
        f"{usp}, white background, studio lighting, "
        f"clean professional look for online store listing, no text"
    )
    generate_image(prompt)


def menu_free():
    print("\n--- Custom Image ---")
    prompt = input("Describe the image you want: ").strip()
    generate_image(prompt)


def main():
    print("=" * 50)
    print("   JK Graphic Design Tool — Powered by Pollinations.ai")
    print("=" * 50)
    print("\nWhat do you want to create?")
    print("  1. Product mockup (for STL file listings)")
    print("  2. Social media graphic (TikTok / YouTube)")
    print("  3. Shopee / Lazada product image")
    print("  4. Custom image (free prompt)")
    print("  0. Exit")

    choice = input("\nChoose (0-4): ").strip()

    if choice == "1":
        menu_product_mockup()
    elif choice == "2":
        menu_social_media()
    elif choice == "3":
        menu_shopee_listing()
    elif choice == "4":
        menu_free()
    elif choice == "0":
        print("Bye!")
        sys.exit(0)
    else:
        print("Invalid choice.")

    again = input("\nCreate another image? (y/n): ").strip().lower()
    if again == "y":
        main()
    else:
        print("\nDone! Check the 'generated_images' folder.")


if __name__ == "__main__":
    main()
