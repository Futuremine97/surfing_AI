"""Adapter between the nightly orchestrator and a minGPT implementation.

Looks for minGPT as an installed `mingpt` package or a local clone at
training/minGPT. All torch imports stay inside functions so the rest of
the pipeline works without torch installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

LOCAL_MINGPT = Path(__file__).parent / "minGPT"


def _load_config(config_path: str) -> dict:
    text = Path(config_path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        # minimal "key: value" parser for flat config files
        config: dict = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                key, _, value = line.partition(":")
                value = value.strip()
                if value.replace(".", "", 1).replace("-", "", 1).isdigit():
                    value = float(value) if "." in value else int(value)
                config[key.strip()] = value
        return config


def _import_mingpt():
    try:
        from mingpt.model import GPT  # type: ignore
        from mingpt.trainer import Trainer  # noqa: F401
        return GPT
    except ImportError:
        if LOCAL_MINGPT.is_dir():
            sys.path.insert(0, str(LOCAL_MINGPT))
            from mingpt.model import GPT  # type: ignore
            return GPT
        raise ImportError(
            "minGPT not found. Either `pip install` a mingpt package or "
            "clone it locally:\n"
            "  git clone https://github.com/karpathy/minGPT training/minGPT")


def build_model(device: str, resume_from: str | None, config_path: str):
    import torch

    config = _load_config(config_path)
    GPT = _import_mingpt()

    model_config = GPT.get_default_config()
    model_config.model_type = str(config.get("model_type", "gpt-mini"))
    model_config.vocab_size = int(config.get("vocab_size", 50257))
    model_config.block_size = int(config.get("block_size", 128))
    model = GPT(model_config)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config.get("learning_rate", 3e-4)),
        weight_decay=float(config.get("weight_decay", 0.1)))

    if resume_from and Path(resume_from).is_file():
        state = torch.load(resume_from, map_location="cpu")
        model.load_state_dict(state["model"])
        if "optimizer" in state:
            optimizer.load_state_dict(state["optimizer"])
        print(f"resumed from {resume_from} "
              f"(stage {state.get('stage', '?')}, "
              f"{state.get('steps_done', 0)} prior steps)")

    model.to(device)
    return model, optimizer


def build_dataloader(config_path: str):
    import torch
    from torch.utils.data import DataLoader, Dataset

    config = _load_config(config_path)
    data_path = Path(str(config.get("dataset_path",
                                    Path(__file__).parent / "data.txt")))
    block_size = int(config.get("block_size", 128))
    batch_size = int(config.get("batch_size", 16))

    if not data_path.is_file():
        raise FileNotFoundError(
            f"dataset not found at {data_path}; set dataset_path in config")

    text = data_path.read_text(encoding="utf-8", errors="ignore")
    chars = sorted(set(text))
    stoi = {ch: i for i, ch in enumerate(chars)}
    data = torch.tensor([stoi[c] for c in text], dtype=torch.long)

    class CharDataset(Dataset):
        def __len__(self):
            return max(1, len(data) - block_size - 1)

        def __getitem__(self, idx):
            chunk = data[idx: idx + block_size + 1]
            return chunk[:-1], chunk[1:]

    return DataLoader(CharDataset(), batch_size=batch_size, shuffle=True,
                      drop_last=True)
