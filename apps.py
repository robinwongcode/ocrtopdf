from flask import Flask, request, send_file
from werkzeug.utils import secure_filename
import pytesseract
from PIL import Image
import os
import tempfile
import logging
import azure.cognitiveservices.vision.computervision as cv
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from msrest.authentication import CognitiveServicesCredentials
import io
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'tiff', 'tif'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

# Azure Computer Vision (fallback if Tesseract not available)
# Set these environment variables in Azure Portal
AZURE_CV_KEY = os.environ.get('DhVh7wl4EiEliwZjkWVolQ4aV7ujcTZr7iLHUQJFmZVS8hesiTINJQQJ99BIACYeBjFXJ3w3AAAFACOGCTuW')
AZURE_CV_ENDPOINT = os.environ.get('https://ocrtopdf.cognitiveservices.azure.com/')


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def image_to_pdf_with_ocr(image_path, output_pdf_path):
    """
    Convert image to PDF with OCR text layer using Tesseract
    """
    try:
        # Create PDF with OCR text
        pdf = pytesseract.image_to_pdf_or_hocr(image_path, extension='pdf')

        # Save PDF
        with open(output_pdf_path, 'wb') as f:
            f.write(pdf)

        return True, "Success"

    except Exception as e:
        return False, str(e)


def azure_ocr_to_pdf(image_path, output_pdf_path):
    """
    Convert image to PDF with OCR using Azure Computer Vision
    """
    try:
        # Check if Azure credentials are available
        if not AZURE_CV_KEY or not AZURE_CV_ENDPOINT:
            return False, "Azure Computer Vision not configured"

        # Authenticate Azure client
        credentials = CognitiveServicesCredentials(AZURE_CV_KEY)
        client = cv.ComputerVisionClient(AZURE_CV_ENDPOINT, credentials)

        # Read image
        with open(image_path, "rb") as image_stream:
            # Submit OCR job
            recognize_headers = dict()
            recognize_headers["Content-Type"] = "application/octet-stream"

            # Call API with raw image data
            recognize_result = client.read_in_stream(
                image=image_stream,
                mode=cv.models.ReadMode.READ,
                raw=True
            )

        # Get operation location (URL with an ID at the end)
        operation_location = recognize_result.headers["Operation-Location"]
        operation_id = operation_location.split("/")[-1]

        # Wait for processing
        while True:
            result = client.get_read_result(operation_id)
            if result.status not in [OperationStatusCodes.running, OperationStatusCodes.not_started]:
                break
            time.sleep(1)

        # If successful, create PDF
        if result.status == OperationStatusCodes.succeeded:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.utils import ImageReader

            # Create PDF with image and text layer
            img = Image.open(image_path)
            img_width, img_height = img.size
            pdf_width, pdf_height = letter

            # Scale image to fit PDF
            scale = min(pdf_width / img_width, pdf_height / img_height)
            img_width *= scale
            img_height *= scale

            # Create PDF
            c = canvas.Canvas(output_pdf_path, pagesize=letter)

            # Add image
            c.drawImage(ImageReader(img), 0, pdf_height - img_height,
                        width=img_width, height=img_height)

            # Add text layer
            for read_result in result.analyze_result.read_results:
                for line in read_result.lines:
                    # Convert bounding box coordinates
                    x = line.bounding_box[0] * scale
                    y = pdf_height - (line.bounding_box[1] * scale)

                    # Add text (invisible but selectable)
                    c.setFillAlpha(0)  # Make text transparent
                    c.setFont("Helvetica", 10)
                    c.drawString(x, y, line.text)

            c.save()
            return True, "Success"
        else:
            return False, f"Azure OCR failed with status: {result.status}"

    except Exception as e:
        return False, str(e)


@app.route('/ocr-to-pdf', methods=['POST'])
def ocr_to_pdf():
    """
    API endpoint to convert image to OCR PDF
    """
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            return {'error': 'No file provided'}, 400

        file = request.files['file']

        # Check if file is selected
        if file.filename == '':
            return {'error': 'No file selected'}, 400

        # Check file type
        if not allowed_file(file.filename):
            return {'error': 'File type not allowed. Supported types: png, jpg, jpeg, bmp, tiff'}, 400

        # Secure filename
        filename = secure_filename(file.filename)

        # Create temporary files
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as input_temp:
            input_path = input_temp.name
            file.save(input_path)

        output_temp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        output_path = output_temp.name
        output_temp.close()

        # Try Tesseract first, fallback to Azure if available
        success, message = image_to_pdf_with_ocr(input_path, output_path)

        if not success:
            logger.warning(f"Tesseract failed: {message}, trying Azure OCR")
            success, message = azure_ocr_to_pdf(input_path, output_path)

        # Clean up input file
        os.unlink(input_path)

        if not success:
            # Clean up output file if it exists
            if os.path.exists(output_path):
                os.unlink(output_path)
            return {'error': f'OCR processing failed: {message}'}, 500

        # Return the PDF file
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f'ocr_output.pdf',
            mimetype='application/pdf'
        )

    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        return {'error': 'Internal server error'}, 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return {'status': 'healthy', 'service': 'OCR to PDF API'}


if __name__ == '__main__':
    # Run the Flask app
    app.run(host='0.0.0.0', port=8000)