# test_api.py
import requests


def test_ocr_api():
    url = "http://localhost:5000/ocr-to-pdf"

    # Replace with your test image path
    image_path = "test_image.jpg"

    with open(image_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(url, files=files)

    if response.status_code == 200:
        # Save the output PDF
        with open('output_ocr.pdf', 'wb') as f:
            f.write(response.content)
        print("OCR PDF created successfully!")
    else:
        print(f"Error: {response.json()}")


if __name__ == "__main__":
    test_ocr_api()