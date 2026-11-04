"""PyTorch MLP (Blueprint p.10, Model A) and its training loop."""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import torch
from sklearn.metrics import average_precision_score
from torch import nn


class StressMLP(nn.Module):
    def __init__(self, n_in: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, 128), nn.ReLU(), nn.LayerNorm(128), nn.Dropout(0.25),
            nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.20),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:   # returns logits
        return self.net(x).squeeze(-1)


@dataclass
class TrainResult:
    model: StressMLP
    best_epoch: int
    holdout_pr_auc: float


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)


def train_one(X: np.ndarray, y: np.ndarray, Xh: np.ndarray, yh: np.ndarray, *, lr: float, weight_decay: float,
              pos_weight: str, seed: int, batch_size: int, max_epochs: int, patience: int) -> TrainResult:
    set_seed(seed)
    model = StressMLP(X.shape[1])
    pw = None
    if pos_weight == "balanced":
        pw = torch.tensor((len(y) - y.sum()) / max(y.sum(), 1), dtype=torch.float32)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pw)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    Xt, yt = torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.float32)
    Xht = torch.tensor(Xh, dtype=torch.float32)
    gen = torch.Generator().manual_seed(seed)

    best = (-1.0, 0, copy.deepcopy(model.state_dict()))
    for epoch in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(len(Xt), generator=gen)
        for i in range(0, len(Xt), batch_size):
            idx = perm[i:i + batch_size]
            opt.zero_grad()
            loss_fn(model(Xt[idx]), yt[idx]).backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            ap = average_precision_score(yh, torch.sigmoid(model(Xht)).numpy())
        if ap > best[0] + 1e-6:
            best = (ap, epoch, copy.deepcopy(model.state_dict()))
        elif epoch - best[1] >= patience:
            break
    model.load_state_dict(best[2])
    model.eval()
    return TrainResult(model, best[1], best[0])


def logits(model: StressMLP, X: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return model(torch.tensor(X, dtype=torch.float32)).numpy().astype(np.float64)


def export_weights(model: StressMLP) -> dict[str, np.ndarray]:
    """Layer names match backend/app/models/inference.py."""
    l1, _, ln, _, l2, _, _, l3, _, l4 = model.net
    t = lambda p: p.detach().numpy().astype(np.float64)  # noqa: E731
    return {"W1": t(l1.weight), "b1": t(l1.bias), "ln_g": t(ln.weight), "ln_b": t(ln.bias),
            "W2": t(l2.weight), "b2": t(l2.bias), "W3": t(l3.weight), "b3": t(l3.bias),
            "W4": t(l4.weight), "b4": t(l4.bias)}
