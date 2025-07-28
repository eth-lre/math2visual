from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import shutil
from datetime import datetime
# import your two existing modules
from generate_visual_language_with_gpt import generate_visual_language
from generate_visual_intuitive import (
    extract_visual_language as extract_intuitive,
    parse_dsl            as parse_intuitive,
    render_svgs_from_data as render_intuitive,
)
from generate_visual_formal import (
    extract_visual_language,
    parse_dsl,
    render_svgs_from_data,
)

app = Flask(__name__)
CORS(app)

@app.route("/api/generate", methods=["POST"])
def generate():
    body = request.json or {}
    # mwp     = body.get("mwp", "").strip()
    # formula = body.get("formula") or None

    # if not mwp:
    #     return jsonify({"error": "Please provide a math word problem (mwp)."}), 400

    # # 1) Ask GPT to produce your DSL
    # vl_response = generate_visual_language(mwp, formula)
    # # vl_response should contain a line like "visual_language: …"
    # raw = extract_visual_language(vl_response)
    # if not raw:
    #     return jsonify({"error": "Could not find `visual_language:` in GPT response."}), 500

    # # 3) Strip off the “visual_language:” prefix
    # #    => we want just “subtraction(container1[…],…)”
    # if raw.lower().startswith("visual_language:"):
    #     dsl = raw.split(":", 1)[1].strip()
    # else:
    #     dsl = raw.strip()
    # if not dsl:
    #     return jsonify({"error": "Could not find `visual_language:` in GPT response."}), 500

    # 2) Parse the DSL into your internal data structure
       # If user supplied a DSL override, use it directly:
    if "dsl" in body:
        raw_dsl = body["dsl"].strip()
        if not raw_dsl:
            return jsonify({"error": "Empty DSL provided."}), 400
        # strip the prefix if present:
        if raw_dsl.lower().startswith("visual_language:"):
            dsl = raw_dsl.split(":", 1)[1].strip()
        else:
            dsl = raw_dsl
    else:
        mwp     = body.get("mwp", "").strip()
        formula = body.get("formula") or None
        if not mwp:
            return jsonify({"error": "Please provide a math word problem (mwp)."}), 400

        # 1) Generate via GPT and extract
        vl_response = generate_visual_language(mwp, formula)
        raw = extract_visual_language(vl_response)
        if not raw:
            return jsonify({"error": "Could not find `visual_language:` in GPT response."}), 500
        dsl = raw.split(":", 1)[1].strip() if raw.lower().startswith("visual_language:") else raw.strip()
    # parse once for formal…
    try:
        data_formal = parse_dsl(dsl)
    except ValueError as e:
        return jsonify({"error": f"Formal-DSL parse error: {e}"}), 500

    # …and once for intuitive
    try:
        data_intuitive = parse_intuitive(dsl)
    except ValueError as e:
        return jsonify({"error": f"Intuitive-DSL parse error: {e}"}), 500

        # 3) Render the SVGs into your “latest” files
    output_dir    = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_file      = os.path.join(output_dir, "output.svg")
    intuitive_file   = os.path.join(output_dir, "intuitive.svg")
    resources        = os.path.join(os.path.dirname(__file__), "svg_dataset")

    # formal
    if os.path.exists(output_file):
        os.remove(output_file)
    ok_formal = render_svgs_from_data(output_file, resources, data_formal)
    formal_error = None
    if ok_formal:
        with open(output_file, "r") as f1:
            svg_formal = f1.read()
    else:
        svg_formal = None
        formal_error = "Could not generate formal visualization."
    
    # 3b) Render Intuitive (non-fatal)
    if os.path.exists(intuitive_file):
        os.remove(intuitive_file)
    ok_intu = render_intuitive(intuitive_file, resources, data_intuitive)
    intuitive_error = None
    if ok_intu:
        with open(intuitive_file, "r") as f2:
            svg_intuitive = f2.read()
    else:
        svg_intuitive = None
        intuitive_error = "Could not generate intuitive visualization."

    # 4) Archive timestamped copies
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    if ok_formal and os.path.exists(output_file):
        shutil.copy(output_file, os.path.join(output_dir, f"formal_{ts}.svg"))
    if ok_intu and os.path.exists(intuitive_file):
        shutil.copy(intuitive_file, os.path.join(output_dir, f"intuitive_{ts}.svg"))

    # 5) Return the DSL and SVG XML with error information
    return jsonify({
        "visual_language": dsl,
        "svg_formal": svg_formal,
        "svg_intuitive": svg_intuitive,
        "formal_error": formal_error,
        "intuitive_error": intuitive_error
    })

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)