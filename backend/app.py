from flask import Flask, request, jsonify
from flask_cors import CORS
import qpic
from io import StringIO
import sys
import tempfile
import subprocess
import base64
import os
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",  # Allow all origins during development
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Content-Type"],
        "supports_credentials": True
    }
})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')  # Allow all origins
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Allow-Methods', '*')
    return response

class Capturing(list):
    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = self._stringio = StringIO()
        return self
    
    def __exit__(self, *args):
        self.extend(self._stringio.getvalue().splitlines())
        del self._stringio
        sys.stdout = self._stdout

def check_dependencies():
    """Check if required command-line tools are installed."""
    try:
        subprocess.run(['pdf2svg', '--version'], capture_output=True)
    except FileNotFoundError:
        logger.error("pdf2svg is not installed. Please install it using:")
        logger.error("  Ubuntu/Debian: sudo apt-get install pdf2svg")
        logger.error("  macOS: brew install pdf2svg")
        return False
    return True

def invoke_qpic(qpic_code):
    if not check_dependencies():
        return {'error': 'pdf2svg is not installed. Please install it first.'}

    try:
        logger.debug(f"Processing qpic code: {qpic_code}")
        
        # Create temp directory for all files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write qpic code to file
            qpic_path = os.path.join(temp_dir, 'input.qpic')
            with open(qpic_path, 'w') as f:
                f.write(qpic_code)
            
            logger.debug(f"Created qpic file at: {qpic_path}")
            
            # Capture qpic output
            with open(qpic_path, 'r') as qpic_file:
                with Capturing() as tikz_output:
                    qpic.main(qpic_file)  # Pass file object instead of path
            
            logger.debug(f"TikZ output: {tikz_output}")
            
            if not tikz_output:
                raise Exception("No output generated from Qpic")
            
            tex_path = os.path.join(temp_dir, 'output.tex')
            pdf_path = os.path.join(temp_dir, 'output.pdf')
            svg_path = os.path.join(temp_dir, 'output.svg')
            
            # Write TeX file
            tex_content = r"""
\documentclass{standalone}
\usepackage{tikz}
\begin{document}
%s
\end{document}
""" % '\n'.join(tikz_output)
            with open(tex_path, 'w') as tex_file:
                tex_file.write(tex_content)
            
            logger.debug(f"Created TeX file at: {tex_path}")
            
            # Run pdflatex
            result = subprocess.run(
                ['pdflatex', '-interaction=nonstopmode', tex_path],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error(f"pdflatex error: {result.stderr}")
                raise Exception(f"PDF conversion failed: {result.stderr}")
            
            # Run pdf2svg
            result = subprocess.run(
                ['pdf2svg', pdf_path, svg_path],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                logger.error(f"pdf2svg error: {result.stderr}")
                raise Exception(f"SVG conversion failed: {result.stderr}")
            
            # Read results
            with open(pdf_path, 'rb') as f:
                pdf_data = base64.b64encode(f.read()).decode('utf-8')
            
            with open(svg_path, 'r') as f:
                svg_data = f.read()
            
            return {
                'tikz': '\n'.join(tikz_output),
                'pdf': pdf_data,
                'svg': svg_data
            }
            
    except Exception as e:
        logger.exception("Error in invoke_qpic")
        return {
            'tikz': '\n'.join(tikz_output) if 'tikz_output' in locals() else '',
            'error': str(e)
        }

@app.route('/check_point')
def checkPoint():
    app.logger.info('Server is OK!')
    return 'Server is OK!'

@app.route('/api/stim-to-qpic', methods=['POST'])
def stim_to_qpic():
    data = request.get_json()
    stim_code = data.get('stimCode')
    if not stim_code:
        return jsonify({"error": "stimCode is required"}), 400
    # Simulate conversion from stim code to qpic code.
    qpic_code = f"Converted Qpic Code: {stim_code}"
    return jsonify({"qpicCode": qpic_code})

@app.route('/api/qpic-to-svg', methods=['POST'])
def qpic_to_svg():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
            
        qpic_code = data.get('qpicCode')
        if not qpic_code:
            return jsonify({"error": "qpicCode is required"}), 400
        
        result = invoke_qpic(qpic_code)
        if 'error' in result:
            return jsonify({"error": result['error']}), 400
            
        return jsonify({
            "svgResult": result['svg'],
            "tikzCode": result['tikz']
        })
    except Exception as e:
        app.logger.error(f"Error processing request: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=3000, debug=True)

