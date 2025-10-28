# <img src="math2visual_title.png" width="24" height="24"> Math2Visual
Generating Pedagogically Meaningful Visuals for Math Word Problems: A New Benchmark and Analysis of Text-to-Image Models, ACL 2025 Findings

📄 **[ACL 2025 Findings Paper — Math2Visual](https://aclanthology.org/2025.findings-acl.586/)**  

🎥 **[ACL 2025 Video](https://youtu.be/jdPYVoHEPtk)**  

📘 **[Annotated Visual Language and Visual Dataset](https://huggingface.co/datasets/junling24/Math2Visual-Generating_Pedagogically_Meaningful_Visuals_for_Math_Word_Problems)**  

🤖 **[Visual Language Generation Model](https://huggingface.co/junling24/Math2Visual-Visual_Language_Generation)**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

# Description
In this project, we present Math2Visual, an automatic framework for generating pedagogically meaningful visuals from math word problem text descriptions. Math2Visual leverages a pre-defined visual language and a design space grounded in interviews with math teachers, to illustrate the core mathematical relationships in math word problems. Using Math2Visual, we construct an annotated dataset of 1,903 visuals and evaluate Text-to-Image (TTI) models for their ability to generate visuals that align with our design. We further fine-tune several TTI models with our dataset, demonstrating improvements in educational visual generation. Our work establishes a new benchmark for automated generation of pedagogically meaningful visuals and offers insights into key challenges in producing multimodal educational content, such as the misrepresentation of mathematical relationships and the omission of essential visual elements.


# Access the Dataset on Hugging Face

We have released the full dataset on Hugging Face, including:
- Annotated visual language with corresponding math word problems
- Generated formal and intuitive visuals in both `.svg` and `.png` formats

👉 **[Browse the dataset on Hugging Face](https://huggingface.co/datasets/junling24/Math2Visual-Generating_Pedagogically_Meaningful_Visuals_for_Math_Word_Problems)**

You can preview images and download files directly from the Hugging Face web interface.

<img src="example_operation_math2visual.png" width="1000" height="1000">


# Generating Your Own Educational Visuals from Math Word Problems!!
## Step 1: Install dependency
```bash
git clone https://github.com/eth-lre/math2visual.git
conda create -n math2visual python=3.12.4
conda activate math2visual
cd math2visual
```
### Option A: Using Our Fine-tuned Model:
```bash
pip install -r requirements_a.txt
```
### Option B: Using OpenAI API:
```bash
pip install -r requirements_b.txt
```

## Step 2: Set your OpenAI key into environment through (you can skip this step if using option A):
```bash
touch .env
echo "OPENAI_API_KEY=<your_openai key>" >> .env
```
## Step 3: Generate visual language from your math word problem 
### Option A: Using Our Fine-tuned Model:
**[Download our model adapter on Hugging Face](https://huggingface.co/junling24/Math2Visual-Visual_Language_Generation)**

Place the adapter_model.safetensors into model/check-point/

**[Download base model meta-llama/Llama-3.1-8B on Hugging Face](https://huggingface.co/meta-llama/Llama-3.1-8B)**

Place the downloaded folder into model/base_model/

Replace the 'mwp' and 'formula' fields with your own math word problem content in generate_visual_language_with_our_model.py (around line 102). Then run:
```bash
python3 generate_visual_language_with_our_model.py
```
It will print out the generated visual language and save it in /output_visual_language/visual_langauge.txt
### Option B: Using OpenAI API:
Replace the 'mwp' and 'formula' fields with your own math word problem content in generate_visual_language_with_gpt.py (around line 196). Then run:
```bash
python3 generate_visual_language_with_gpt.py
```
It will print out the generated visual language and save it in /output_visual_language/visual_langauge.txt

## Step 4: Generate "formal visual" from visual language
Replace the 'visual_language' field with your own generated visual language in generate_visual_formal.py (around line 1406). Then run:
```bash
python3 generate_visual_formal.py
```
It will generate the visual and save it in /output_visual_formal/01.svg

## Step 5: Generate "intuitive visual" from visual language
Replace the 'visual_language' field with your own generated visual language in generate_visual_intuitive.py (around line 4263). Then run:
```bash
python3 generate_visual_intuitive.py
```
It will generate the visual and save it in /output_visual_intuitive/01.svg


# Citation
Junling Wang, Anna Rutkiewicz, April Wang, and Mrinmaya Sachan. 2025. Generating Pedagogically Meaningful Visuals for Math Word Problems: A New Benchmark and Analysis of Text-to-Image Models. In Findings of the Association for Computational Linguistics: ACL 2025, pages 11229–11257, Vienna, Austria. Association for Computational Linguistics.

```bibtex
@inproceedings{wang-etal-2025-generating-pedagogically,
    title = "Generating Pedagogically Meaningful Visuals for Math Word Problems: A New Benchmark and Analysis of Text-to-Image Models",
    author = "Wang, Junling  and
      Rutkiewicz, Anna  and
      Wang, April  and
      Sachan, Mrinmaya",
    editor = "Che, Wanxiang  and
      Nabende, Joyce  and
      Shutova, Ekaterina  and
      Pilehvar, Mohammad Taher",
    booktitle = "Findings of the Association for Computational Linguistics: ACL 2025",
    month = jul,
    year = "2025",
    address = "Vienna, Austria",
    publisher = "Association for Computational Linguistics",
    url = "https://aclanthology.org/2025.findings-acl.586/",
    pages = "11229--11257",
    ISBN = "979-8-89176-256-5",
    abstract = "Visuals are valuable tools for teaching math word problems (MWPs), helping young learners interpret textual descriptions into mathematical expressions before solving them.However, creating such visuals is labor-intensive and there is a lack of automated methods to support this process. In this paper, we present Math2Visual, an automatic framework for generating pedagogically meaningful visuals from MWP text descriptions. Math2Visual leverages a pre-defined visual language and a design space grounded in interviews with math teachers, to illustrate the core mathematical relationships in MWPs.Using Math2Visual, we construct an annotated dataset of 1,903 visuals and evaluate Text-to-Image (TTI) models for their ability to generate visuals that align with our design. We further fine-tune several TTI models with our dataset, demonstrating improvements in educational visual generation. Our work establishes a new benchmark for automated generation of pedagogically meaningful visuals and offers insights into key challenges in producing multimodal educational content, such as the misrepresentation of mathematical relationships and the omission of essential visual elements."
}
```

---
This work is licensed under a
This work is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).  
For research inquiries, please contact: Junling Wang — wangjun [at] ethz [dot] ch


[cc-by-sa]: http://creativecommons.org/licenses/by-sa/4.0/
[cc-by-sa-shield]: https://img.shields.io/badge/License-CC%20BY--SA%204.0-lightgrey.svg
