import os
import argparse
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel

# --- Prompt construction ---
def create_prompt(mwp: str, formula: str = None) -> str:
    prompt_text = (
    '''You are an expert at converting math story problem into a structured 'visual language'. Your task is to write a visual language expression based on the given math story problem. 
    **Background information**
    You shoud use the following fixed format for each problem:
    <operation>(
    container1[entity_name: <entity name>, entity_type: <entity type>, entity_quantity: <number of this entity in this container>, container_name: <container name>, container_type: <container type>, attr_name: <attribute name>, attr_type: <attribute type>],
    container2[entity_name: <entity name>, entity_type: <entity type>, entity_quantity: <number of this entity in this container>, container_name: <container name>, container_type: <container type>, attr_name: <attribute name>, attr_type: <attribute type>],
    result_container[entity_name: <entity name>, entity_type: <entity type>, entity_quantity: <number of this entity in this container>, container_name: <container name>, container_type: <container type>, attr_name: <attribute name>, attr_type: <attribute type>]
    )                
    operation can be ``addition'', ``subtraction'', ``multiplication'', ``division'', ``surplus'', ``area'', ``comparison'', or ``unittrans''.
    Each entity has the attributes: entity_name, entity_type, entity_quantity, container_name, container_type, attr_name, attr_type. Name and type are different, for example, a girl named Lucy may be represented by entity_name: Lucy, entity_type: girl. The attributes container_name, container_type, attr_name and attr_type are optional and may vary according to different interpretations, only use them if you think they are necessary to clarify the entity.
    In the math word problem description ``Jake picked up three apples in the morning...'' the container1 could be specified as entity_name: apple, entity_type: apple, entity_quantity: 3, container_name: Jake, container_type: boy, attr_name: morning, attr_type: morning. 
    
    Good, now try to understand the above requirement step by step. I also provide you with the formula of this question, your visual_language should adapt to this formula, for example, if the formula is multiple addition instead of multiplication, you should use multiple addition. 
    Once you are ready, you can do the task of converting, please make sure to give me the final visual language of the following question in this format only: visual_language:<the visual language result>'''
    f"Question: {mwp}\n"
    f"Formula: {formula}\n"
    "Answer in visual language:")

    return prompt_text

# --- Generator class ---
class VisualLanguageGenerator:
    def __init__(self, base_model_id: str, adapter_dir: str):
        # Quantization config
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        # Load base model
        print("Loading base model...")
        base = AutoModelForCausalLM.from_pretrained(
            base_model_id,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True
        )
        # Load PEFT adapter
        print("Loading fine-tuned adapter...")
        self.model = PeftModel.from_pretrained(base, adapter_dir)
        self.model.eval()
        self.model.config.use_cache = True

        # Load tokenizer
        print("Loading tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            base_model_id,
            padding_side="left",
            add_eos_token=True,
            add_bos_token=True,
            trust_remote_code=True
        )
        self.tokenizer.pad_token = self.tokenizer.eos_token

        # Set device
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)

    def generate(self,
                 mwp: str,
                 formula: str = None,
                 max_length: int = 2048,
                 max_new_tokens: int = 2048,
                 temperature: float = 0.7,
                 repetition_penalty: float = 1.15
    ) -> str:
        prompt = create_prompt(mwp, formula)
        inputs = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
            padding="max_length"
        ).to(self.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,
                temperature=temperature,
                repetition_penalty=repetition_penalty
            )

        full_output = self.tokenizer.decode(generated_ids[0], skip_special_tokens=True)
        # strip off the prompt prefix
        return full_output[len(prompt):].strip()

# --- Main entrypoint with fixed defaults ---
if __name__ == "__main__":
    # Default parameters (edit as needed)
    mwp = "Janet has nine oranges, and Sharon has seven oranges. How many oranges do Janet and Sharon have together?"
    formula = "9 + 7 = 16" 
    base_model_id = "./base_model/models--meta-llama--Llama-3.1-8B/snapshots/d04e592bb4f6aa9cfee91e2e20afa771667e1d4b"
    adapter_dir = "./check-point"
    max_length = 2048
    max_new_tokens = 2048
    # Generate visual language
    gen = VisualLanguageGenerator(base_model_id, adapter_dir)
    vl = gen.generate(mwp, formula, max_length, max_new_tokens)

    # Save to file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(current_dir, 'output_visual_language')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'visual_language.txt')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(vl)

    # Print result
    print(vl)