"""Embeddings of the motion phase sentences (LLM2Vec on Llama-3-8B in 4 bits, GPU) into a .pt file; sentences already in the file are reused.
Run with Kimodo's Python: $KIMODO_PYTHON pipeline/motion/kimodo_text.py --motion <motion>.json --out emb.pt
Llama is loaded by hand with the PEFT adapters: LLM2Vec.from_pretrained fails with bitsandbytes."""
import argparse, json, os, sys

ap = argparse.ArgumentParser(description="Encode motion phase sentences with LLM2Vec (Llama-3-8B, 4-bit).")
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True)
A = ap.parse_args()

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import kimodo_common
# transformers 5 loads weights in 4 threads: with ~10 GB of free committed memory -> access violation in c10/torch_cpu
# without a traceback (6 tries); sequential loading works.
os.environ.setdefault("HF_DEACTIVATE_ASYNC_LOAD", "1")
kimodo_common.setup(os.path.basename(__file__))
import torch
from transformers import AutoTokenizer, BitsAndBytesConfig
from peft import PeftModel
from kimodo.model.llm2vec.llm2vec import LLM2Vec

texts = [f["text"] for f in json.load(open(A.motion, encoding="utf-8"))["phases"]]
res = torch.load(A.out) if os.path.exists(A.out) else {}
missing = [t for t in dict.fromkeys(texts) if t not in res]
if not missing:
    print("OK (all sentences already in the file)", A.out); sys.exit(0)

q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
MN = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"
tok = AutoTokenizer.from_pretrained(MN); tok.pad_token = tok.eos_token; tok.padding_side = "left"
cls = LLM2Vec._get_model_class("LlamaConfig", enable_bidirectional=True)
base = cls.from_pretrained("meta-llama/Meta-Llama-3-8B-Instruct", quantization_config=q, device_map="cuda:0",
                           torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
base = PeftModel.from_pretrained(base, MN).merge_and_unload()
base = PeftModel.from_pretrained(base, MN + "-supervised")
m = LLM2Vec(model=base, tokenizer=tok); m.eval()
with torch.no_grad():
    for t in missing:
        res[t] = torch.as_tensor(m.encode([t], batch_size=1, show_progress_bar=False, device="cuda:0")).float().cpu()
        print("+", t[:70])
torch.save(res, A.out)
print("OK", A.out, "VRAM %.1f GB" % (torch.cuda.max_memory_allocated() / 1e9))
