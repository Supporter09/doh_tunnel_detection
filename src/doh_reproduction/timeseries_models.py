"""PyTorch time-series model factories, training routines, Platt calibration, and metric helpers.

This module provides two distinct model families:
1. Paper Reference Model (`PaperReferenceLSTMModel` / `create_paper_model`):
   Faithful reconstruction of the DoHLyzer `v4.py` reference architecture
   (Dense(5->10, ReLU) per step -> LSTM(10->8*l) -> Dense(8*l->6*l, ReLU) ->
    Dropout(0.2) -> Dense(6*l->2*l, ReLU) -> Dense(2*l->1, Sigmoid)).
   Architecture details are ground-truth facts from the DoHLyzer reference code
   (UNB CIC / Arash Habibi Lashkari et al.).
   NOTE: MontazeriShatoori et al. (IEEE CyberSciTech 2020) omitted training
   hyperparameters (optimizer, learning rate, batch size, epoch budget, early stopping).
   All training hyperparameters (Adam, lr=1e-3, batch_size=64, patience=5) are project
   engineering choices for reproduction and are NEVER claimed to be paper specifications.

2. Improved Candidate Model (`ImprovedMaskedBiGRUModel` / `create_improved_model`):
   Modern defensive alternative using mask-aware bidirectional GRU with attention
   pooling over valid clumps (masking out [-1, -1, -1, -1, 0] padding),
   class-weighted binary cross-entropy, and validation-only Platt/threshold selection.
   This model is architecturally separate and never masquerades as the paper model.

All PyTorch dependencies are imported lazily and safely. Pure threshold selection,
Platt calibration, confusion matrix counting, and binary classification metrics
operate on standard Python sequences/arrays and remain fully functional even when
PyTorch or scikit-learn are absent.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

# Attempt lazy imports for numpy, torch, and sklearn
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    NUMPY_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False

try:
    import sklearn
    import sklearn.metrics
    SKLEARN_AVAILABLE = True
except ImportError:
    sklearn = None  # type: ignore[assignment]
    SKLEARN_AVAILABLE = False


# Canonical padding vector per DoHLyzer dataset.py
PADDING_VECTOR = (-1.0, -1.0, -1.0, -1.0, 0.0)


def is_torch_available() -> bool:
    """Return True if PyTorch is available in the current runtime environment."""
    return TORCH_AVAILABLE


def require_torch(caller: str = "This operation") -> None:
    """Raise an actionable ImportError when a PyTorch-dependent component is requested."""
    if not TORCH_AVAILABLE:
        raise ImportError(
            f"{caller} requires PyTorch ('torch'). "
            "Please install PyTorch via 'pip install torch' or run within an environment "
            "where PyTorch is installed (such as the Kaggle runner)."
        )


def set_deterministic_seed(seed: int = 42) -> None:
    """Set random seeds across Python random, NumPy, and PyTorch for reproducible runs."""
    random.seed(seed)
    if NUMPY_AVAILABLE and np is not None:
        np.random.seed(seed)
    if TORCH_AVAILABLE and torch is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False


# ---------------------------------------------------------------------------
# Model Architecture Classes
# ---------------------------------------------------------------------------
def get_paper_model_dimensions(window_size: int) -> dict[str, Any]:
    """Return the exact layer dimensions for the DoHLyzer v4 paper reference model.

    This pure helper does not require PyTorch and computes the exact layer topology:
    - Step Dense: Linear(5, 10), ReLU per clump time step
    - LSTM core: LSTM(input_size=10, hidden_size=8*window_size)
    - Dense 1: Linear(8*window_size, 6*window_size), ReLU
    - Dropout: Dropout(p=0.2)
    - Dense 2: Linear(6*window_size, 2*window_size), ReLU
    - Output: Linear(2*window_size, 1), Sigmoid

    Args:
        window_size: Number of clumps per sequence segment (>= 1).

    Returns:
        Dictionary mapping layer name to dimension specification.
    """
    if window_size < 1:
        raise ValueError(f"window_size must be >= 1, got {window_size}")
    w = int(window_size)
    return {
        "step_dense": (5, 10),
        "lstm_input": 10,
        "lstm_hidden": 8 * w,
        "dense1": (8 * w, 6 * w),
        "dropout_p": 0.2,
        "dense2": (6 * w, 2 * w),
        "out_proj": (2 * w, 1),
    }


def get_improved_model_dimensions(
    window_size: int,
    hidden_dim: int = 64,
    num_layers: int = 1,
    dropout: float = 0.2,
) -> dict[str, Any]:
    """Return layer dimensions for the improved mask-aware BiGRU attention model.

    This pure helper does not require PyTorch.

    Args:
        window_size: Number of clumps per sequence segment (>= 1).
        hidden_dim: Hidden dimension per GRU direction.
        num_layers: Number of GRU layers.
        dropout: Dropout rate.

    Returns:
        Dictionary mapping component to dimension specification.
    """
    if window_size < 1:
        raise ValueError(f"window_size must be >= 1, got {window_size}")
    h = int(hidden_dim)
    n = int(num_layers)
    return {
        "input_dim": 5,
        "gru_hidden_dim": h,
        "gru_directions": 2,
        "gru_num_layers": n,
        "context_dim": 2 * h,
        "attn_proj": (2 * h, h),
        "fc1": (2 * h, h),
        "fc2": (h, 1),
        "dropout_p": float(dropout),
    }


class _PaperReferenceLSTMFallback:
    """Actionable fallback stub when PyTorch is not installed."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        require_torch("PaperReferenceLSTMModel")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        require_torch("PaperReferenceLSTMModel")


class _ImprovedMaskedBiGRUFallback:
    """Actionable fallback stub when PyTorch is not installed."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        require_torch("ImprovedMaskedBiGRUModel")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        require_torch("ImprovedMaskedBiGRUModel")


if TORCH_AVAILABLE:

    class PaperReferenceLSTMModel(nn.Module):
        """Reconstruction of DoHLyzer reference v4.py sequential architecture.

        Topology:
            - Step Dense: Linear(5, 10), ReLU per time step
            - LSTM core: LSTM(input_size=10, hidden_size=8*window_size, batch_first=True)
            - Dense 1: Linear(8*window_size, 6*window_size), ReLU
            - Dropout: Dropout(p=0.2)
            - Dense 2: Linear(6*window_size, 2*window_size), ReLU
            - Output: Linear(2*window_size, 1), Sigmoid for probabilities

        Layer dimensions:
            - For l=3: 5 -> 10 -> LSTM(24) -> 18 -> Dropout(0.2) -> 6 -> 1
            - For l=6: 5 -> 10 -> LSTM(48) -> 36 -> Dropout(0.2) -> 12 -> 1
        """

        model_type: str = "paper_reference_v4"

        def __init__(self, window_size: int) -> None:
            super().__init__()
            if window_size < 1:
                raise ValueError(f"window_size must be >= 1, got {window_size}")

            self.window_size: int = int(window_size)
            l = self.window_size

            # Step 1: Dense(10, ReLU) per time step
            self.step_dense = nn.Linear(5, 10)
            self.step_relu = nn.ReLU()

            # Step 2: LSTM(8*l)
            self.lstm = nn.LSTM(
                input_size=10,
                hidden_size=8 * l,
                batch_first=True,
            )

            # Step 3: Dense(6*l, ReLU)
            self.dense1 = nn.Linear(8 * l, 6 * l)
            self.dense1_relu = nn.ReLU()

            # Step 4: Dropout(0.2)
            self.dropout = nn.Dropout(p=0.2)

            # Step 5: Dense(2*l, ReLU)
            self.dense2 = nn.Linear(6 * l, 2 * l)
            self.dense2_relu = nn.ReLU()

            # Step 6: Output Dense(1, Sigmoid)
            self.out_proj = nn.Linear(2 * l, 1)
            self.sigmoid = nn.Sigmoid()

        def forward(
            self,
            x: torch.Tensor,
            return_probs: bool = False,
        ) -> torch.Tensor:
            """Forward pass.

            Args:
                x: Input tensor of shape (batch_size, window_size, 5).
                return_probs: If True, applies sigmoid to return [0, 1] probabilities;
                              if False, returns raw logits (for BCEWithLogitsLoss).

            Returns:
                Tensor of shape (batch_size, 1) containing logits or probabilities.
            """
            if x.dim() == 2:
                x = x.unsqueeze(0)
            if x.shape[-1] != 5:
                raise ValueError(f"Expected last dimension 5, got {x.shape[-1]}")

            # 1. Step-wise projection: (batch, seq, 5) -> (batch, seq, 10)
            step_out = self.step_relu(self.step_dense(x))

            # 2. LSTM: (batch, seq, 10) -> (batch, seq, 8*l)
            lstm_out, (hn, _cn) = self.lstm(step_out)

            # Take last time step output per Keras return_sequences=False semantics
            h_last = lstm_out[:, -1, :]  # shape (batch, 8*l)

            # 3. Dense 1: (batch, 8*l) -> (batch, 6*l)
            d1 = self.dense1_relu(self.dense1(h_last))

            # 4. Dropout
            d1_drop = self.dropout(d1)

            # 5. Dense 2: (batch, 6*l) -> (batch, 2*l)
            d2 = self.dense2_relu(self.dense2(d1_drop))

            # 6. Logits: (batch, 2*l) -> (batch, 1)
            logits = self.out_proj(d2)

            if return_probs:
                return self.sigmoid(logits)
            return logits

        def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
            """Return binary probabilities P(y=1) in [0, 1]."""
            return self.forward(x, return_probs=True).squeeze(-1)


    class ImprovedMaskedBiGRUModel(nn.Module):
        """Improved candidate: mask-aware bidirectional GRU with attention pooling.

        Features:
            - Bidirectional GRU capturing both forward and backward clump contexts.
            - Mask-aware attention pooling that explicitly ignores padding vectors
              ([-1, -1, -1, -1, 0]) by masking attention scores to -inf prior to softmax.
            - Configurable hidden dimension and dropout.
            - Numerically stable logits output with optional sigmoid probability extraction.
            - Distinct class and architecture name from paper reference model.
        """

        model_type: str = "improved_masked_bigru"

        def __init__(
            self,
            window_size: int,
            hidden_dim: int = 64,
            num_layers: int = 1,
            dropout: float = 0.2,
        ) -> None:
            super().__init__()
            if window_size < 1:
                raise ValueError(f"window_size must be >= 1, got {window_size}")
            if hidden_dim < 4:
                raise ValueError(f"hidden_dim must be >= 4, got {hidden_dim}")

            self.window_size: int = int(window_size)
            self.hidden_dim: int = int(hidden_dim)
            self.num_layers: int = int(num_layers)
            self.dropout_rate: float = float(dropout)

            # Bidirectional GRU
            self.gru = nn.GRU(
                input_size=5,
                hidden_size=self.hidden_dim,
                num_layers=self.num_layers,
                batch_first=True,
                bidirectional=True,
                dropout=self.dropout_rate if self.num_layers > 1 else 0.0,
            )

            # Attention pooling: projects 2*hidden_dim -> hidden_dim -> 1 scalar score per step
            self.attn_proj = nn.Linear(2 * self.hidden_dim, self.hidden_dim)
            self.attn_act = nn.Tanh()
            self.attn_v = nn.Linear(self.hidden_dim, 1, bias=False)

            # Classification head
            self.fc1 = nn.Linear(2 * self.hidden_dim, self.hidden_dim)
            self.fc1_act = nn.ReLU()
            self.dropout = nn.Dropout(p=self.dropout_rate)
            self.fc2 = nn.Linear(self.hidden_dim, 1)
            self.sigmoid = nn.Sigmoid()

        def compute_padding_mask(self, x: torch.Tensor) -> torch.Tensor:
            """Detect DoHLyzer padding vectors [-1, -1, -1, -1, 0].

            Returns:
                Boolean tensor of shape (batch_size, seq_len) where True denotes a
                VALID (non-padded) clump and False denotes a padded clump.
            """
            pad_val = torch.tensor(PADDING_VECTOR, dtype=x.dtype, device=x.device)
            is_pad = torch.isclose(x, pad_val, atol=1e-4).all(dim=-1)
            valid_mask = ~is_pad

            # Guard: if an entire sequence is padding, preserve all steps to avoid div-by-zero
            all_pad = ~valid_mask.any(dim=-1, keepdim=True)
            valid_mask = torch.where(all_pad, torch.ones_like(valid_mask), valid_mask)
            return valid_mask

        def forward(
            self,
            x: torch.Tensor,
            mask: Optional[torch.Tensor] = None,
            return_probs: bool = False,
            return_attention: bool = False,
        ) -> Union[torch.Tensor, Tuple[torch.Tensor, torch.Tensor]]:
            """Forward pass with mask-aware attention pooling.

            Args:
                x: Input tensor of shape (batch_size, seq_len, 5).
                mask: Optional boolean tensor of shape (batch_size, seq_len) where True
                      indicates valid clumps. If None, auto-detected from padding vectors.
                return_probs: Return probabilities instead of raw logits.
                return_attention: If True, returns (output, attention_weights).

            Returns:
                Tensor of shape (batch_size, 1) or tuple (output, attn_weights).
            """
            if x.dim() == 2:
                x = x.unsqueeze(0)
            if x.shape[-1] != 5:
                raise ValueError(f"Expected last dimension 5, got {x.shape[-1]}")

            # 1. Determine valid mask
            if mask is None:
                valid_mask = self.compute_padding_mask(x)
            else:
                if mask.dtype == torch.bool:
                    valid_mask = mask
                else:
                    valid_mask = mask > 0.5
                all_pad = ~valid_mask.any(dim=-1, keepdim=True)
                valid_mask = torch.where(all_pad, torch.ones_like(valid_mask), valid_mask)

            # 2. BiGRU: (batch, seq, 5) -> (batch, seq, 2*hidden_dim)
            gru_out, _ = self.gru(x)

            # 3. Attention pooling with padding masking
            # Project to hidden_dim then scalar score
            u = self.attn_act(self.attn_proj(gru_out))  # (batch, seq, hidden_dim)
            attn_scores = self.attn_v(u)                # (batch, seq, 1)

            # Mask out padding: set scores of padded steps to large negative value
            mask_expanded = valid_mask.unsqueeze(-1)    # (batch, seq, 1)
            attn_scores = attn_scores.masked_fill(~mask_expanded, -1e9)

            attn_weights = torch.softmax(attn_scores, dim=1)  # (batch, seq, 1)

            # Pooled context vector: sum over time steps
            context = torch.sum(attn_weights * gru_out, dim=1)  # (batch, 2*hidden_dim)

            # 4. Dense classification head
            h = self.fc1_act(self.fc1(context))
            h = self.dropout(h)
            logits = self.fc2(h)  # (batch, 1)

            out = self.sigmoid(logits) if return_probs else logits

            if return_attention:
                return out, attn_weights.squeeze(-1)
            return out

        def predict_proba(
            self,
            x: torch.Tensor,
            mask: Optional[torch.Tensor] = None,
        ) -> torch.Tensor:
            """Return binary probabilities P(y=1) in [0, 1]."""
            out = self.forward(x, mask=mask, return_probs=True)
            if isinstance(out, tuple):
                out = out[0]
            return out.squeeze(-1)

else:
    # Actionable fallback stubs when PyTorch is absent
    PaperReferenceLSTMModel = _PaperReferenceLSTMFallback  # type: ignore[assignment,misc]
    ImprovedMaskedBiGRUModel = _ImprovedMaskedBiGRUFallback  # type: ignore[assignment,misc]

def create_paper_model(
    window_size: int,
    relu_lstm: bool = False,
) -> PaperReferenceLSTMModel:
    """Instantiate the paper-reference DoHLyzer v4 sequential model.

    Args:
        window_size: Number of clumps per sequence segment (e.g. 6 for Layer 1, 3 for Layer 2).
        relu_lstm: Flag reserved for architectural ablation (PyTorch nn.LSTM natively uses tanh;
                   v4.py specified activation='relu').

    Returns:
        Instantiated PaperReferenceLSTMModel.
    """
    require_torch("create_paper_model")
    return PaperReferenceLSTMModel(window_size=window_size)


def create_improved_model(
    window_size: int,
    hidden_dim: int = 64,
    num_layers: int = 1,
    dropout: float = 0.2,
) -> ImprovedMaskedBiGRUModel:
    """Instantiate the improved mask-aware bidirectional GRU attention model.

    Args:
        window_size: Number of clumps per sequence segment.
        hidden_dim: Hidden dimension per GRU direction (total pooled context = 2 * hidden_dim).
        num_layers: Number of GRU layers.
        dropout: Dropout rate applied to context and GRU.

    Returns:
        Instantiated ImprovedMaskedBiGRUModel.
    """
    require_torch("create_improved_model")
    return ImprovedMaskedBiGRUModel(
        window_size=window_size,
        hidden_dim=hidden_dim,
        num_layers=num_layers,
        dropout=dropout,
    )

create_paper_model.get_dimensions = get_paper_model_dimensions  # type: ignore[attr-defined]
create_improved_model.get_dimensions = get_improved_model_dimensions  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Loss Configuration & PyTorch Training / Inference Helpers
# ---------------------------------------------------------------------------

def configure_bce_loss(
    pos_weight: Optional[float] = None,
    reduction: str = "mean",
) -> Any:
    """Configure numerically stable BCEWithLogitsLoss with optional positive class weighting.

    Args:
        pos_weight: Ratio of negative to positive samples (N_neg / N_pos) to penalize
                    false negatives on imbalanced sets.
        reduction: Reduction method ('mean', 'sum', 'none').

    Returns:
        torch.nn.BCEWithLogitsLoss instance.
    """
    require_torch("configure_bce_loss")
    if pos_weight is not None:
        weight_tensor = torch.tensor([float(pos_weight)], dtype=torch.float32)
        return nn.BCEWithLogitsLoss(pos_weight=weight_tensor, reduction=reduction)
    return nn.BCEWithLogitsLoss(reduction=reduction)


def fit_model(
    model: Any,
    train_loader: Any,
    val_loader: Any = None,
    epochs: int = 20,
    lr: float = 1e-3,
    weight_decay: float = 1e-4,
    pos_weight: Optional[float] = None,
    patience: int = 5,
    device: str = "cpu",
    target_fpr: float = 0.001,
) -> dict[str, list[Any]]:
    """Train a PyTorch model with Adam optimizer, early stopping, and history tracking.

    Args:
        model: PyTorch Module (PaperReferenceLSTMModel or ImprovedMaskedBiGRUModel).
        train_loader: Iterable yielding (x, y) or (x, y, mask) or dict batches.
        val_loader: Optional validation loader for early stopping and threshold selection.
        epochs: Maximum number of training epochs.
        lr: Learning rate for Adam optimizer.
        weight_decay: L2 regularization penalty.
        pos_weight: Positive class weight for loss function.
        patience: Number of epochs without validation loss improvement before early stop.
        device: Device string ('cpu', 'cuda', etc.).
        target_fpr: Operational FPR threshold used for validation threshold monitoring.

    Returns:
        History dictionary containing per-epoch loss and evaluation metrics.
    """
    require_torch("fit_model")

    dev = torch.device(device)
    model.to(dev)

    criterion = configure_bce_loss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    history: dict[str, list[Any]] = {
        "epoch": [],
        "train_loss": [],
        "val_loss": [],
        "val_f1": [],
        "val_precision": [],
        "val_recall": [],
        "val_fpr": [],
    }

    best_val_loss = float("inf")
    best_weights = copy.deepcopy(model.state_dict())
    patience_counter = 0

    def unpack_batch(batch: Any) -> Tuple[torch.Tensor, torch.Tensor, Optional[torch.Tensor]]:
        if isinstance(batch, (tuple, list)):
            if len(batch) == 2:
                bx, by = batch
                return bx.to(dev, dtype=torch.float32), by.to(dev, dtype=torch.float32), None
            elif len(batch) >= 3:
                bx, by, bmask = batch[0], batch[1], batch[2]
                bmask_t = bmask.to(dev) if bmask is not None else None
                return bx.to(dev, dtype=torch.float32), by.to(dev, dtype=torch.float32), bmask_t
        elif isinstance(batch, dict):
            bx = batch["x"].to(dev, dtype=torch.float32)
            by = batch["y"].to(dev, dtype=torch.float32)
            bmask = batch.get("mask")
            bmask_t = bmask.to(dev) if bmask is not None else None
            return bx, by, bmask_t
        raise ValueError(f"Unsupported batch format: {type(batch)}")

    for epoch in range(1, epochs + 1):
        model.train()
        train_losses: list[float] = []

        for batch in train_loader:
            bx, by, bmask = unpack_batch(batch)
            optimizer.zero_grad()

            if hasattr(model, "model_type") and model.model_type == "improved_masked_bigru":
                logits = model(bx, mask=bmask, return_probs=False)
            else:
                logits = model(bx, return_probs=False)

            loss = criterion(logits.view(-1), by.view(-1))
            loss.backward()
            optimizer.step()
            train_losses.append(float(loss.item()))

        avg_train_loss = float(sum(train_losses) / max(len(train_losses), 1))
        history["epoch"].append(epoch)
        history["train_loss"].append(avg_train_loss)

        if val_loader is not None:
            model.eval()
            val_losses: list[float] = []
            val_preds_list: list[float] = []
            val_true_list: list[int] = []

            with torch.no_grad():
                for batch in val_loader:
                    bx, by, bmask = unpack_batch(batch)
                    if hasattr(model, "model_type") and model.model_type == "improved_masked_bigru":
                        logits = model(bx, mask=bmask, return_probs=False)
                    else:
                        logits = model(bx, return_probs=False)

                    v_loss = criterion(logits.view(-1), by.view(-1))
                    val_losses.append(float(v_loss.item()))

                    probs = torch.sigmoid(logits.view(-1)).cpu().tolist()
                    val_preds_list.extend(probs)
                    val_true_list.extend([int(x) for x in by.view(-1).cpu().tolist()])

            avg_val_loss = float(sum(val_losses) / max(len(val_losses), 1))
            history["val_loss"].append(avg_val_loss)

            # Evaluate metrics at default 0.5 threshold for epoch logging
            y_pred_binary = [1 if p >= 0.5 else 0 for p in val_preds_list]
            metrics = binary_metrics(val_true_list, y_pred_binary, val_preds_list)
            history["val_f1"].append(metrics["f1"])
            history["val_precision"].append(metrics["precision"])
            history["val_recall"].append(metrics["recall"])
            history["val_fpr"].append(metrics["fpr"])

            # Early stopping check on validation loss
            if avg_val_loss < best_val_loss - 1e-5:
                best_val_loss = avg_val_loss
                best_weights = copy.deepcopy(model.state_dict())
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break
        else:
            history["val_loss"].append(None)
            history["val_f1"].append(None)
            history["val_precision"].append(None)
            history["val_recall"].append(None)
            history["val_fpr"].append(None)

    # Restore best weights if validation was performed
    if val_loader is not None and best_weights:
        model.load_state_dict(best_weights)

    return history


def predict_probabilities(
    model: Any,
    data_or_loader: Any,
    device: str = "cpu",
    batch_size: int = 64,
) -> Any:
    """Generate continuous P(y=1) probability scores from a PyTorch model.

    Args:
        model: PyTorch Module.
        data_or_loader: DataLoader, Iterable, torch.Tensor, np.ndarray, or list of vectors.
        device: Device string ('cpu', 'cuda', etc.).
        batch_size: Mini-batch size when converting raw tensors/arrays.

    Returns:
        1D numpy array of float probabilities in [0.0, 1.0] (or list of floats if numpy absent).
    """
    require_torch("predict_probabilities")

    dev = torch.device(device)
    model.eval()
    model.to(dev)

    all_probs: list[float] = []

    # Case 1: DataLoader or iterable yielding batches
    if hasattr(data_or_loader, "__iter__") and not isinstance(
        data_or_loader, (list, tuple, torch.Tensor, getattr(np, "ndarray", ()))
    ):
        with torch.no_grad():
            for batch in data_or_loader:
                if isinstance(batch, (tuple, list)):
                    bx = batch[0].to(dev, dtype=torch.float32)
                    bmask = batch[2].to(dev) if len(batch) >= 3 and batch[2] is not None else None
                elif isinstance(batch, dict):
                    bx = batch["x"].to(dev, dtype=torch.float32)
                    bmask = batch.get("mask")
                    bmask = bmask.to(dev) if bmask is not None else None
                elif isinstance(batch, torch.Tensor):
                    bx = batch.to(dev, dtype=torch.float32)
                    bmask = None
                else:
                    raise ValueError(f"Unexpected batch type: {type(batch)}")

                if hasattr(model, "model_type") and model.model_type == "improved_masked_bigru":
                    logits = model(bx, mask=bmask, return_probs=False)
                else:
                    logits = model(bx, return_probs=False)

                probs = torch.sigmoid(logits.view(-1)).cpu().tolist()
                all_probs.extend(probs)
    else:
        # Case 2: In-memory Tensor, NumPy array, or Python sequence
        if isinstance(data_or_loader, torch.Tensor):
            t_data = data_or_loader.float()
        elif NUMPY_AVAILABLE and np is not None and isinstance(data_or_loader, np.ndarray):
            t_data = torch.from_numpy(data_or_loader).float()
        else:
            t_data = torch.tensor(data_or_loader, dtype=torch.float32)

        if t_data.dim() == 2:
            t_data = t_data.unsqueeze(0)

        n_samples = t_data.shape[0]
        with torch.no_grad():
            for i in range(0, n_samples, batch_size):
                chunk = t_data[i : i + batch_size].to(dev)
                if hasattr(model, "model_type") and model.model_type == "improved_masked_bigru":
                    logits = model(chunk, return_probs=False)
                else:
                    logits = model(chunk, return_probs=False)
                probs = torch.sigmoid(logits.view(-1)).cpu().tolist()
                all_probs.extend(probs)

    if NUMPY_AVAILABLE and np is not None:
        return np.asarray(all_probs, dtype=np.float64)
    return all_probs


# ---------------------------------------------------------------------------
# Pure Platt Calibration (Zero Dependency)
# ---------------------------------------------------------------------------

@dataclass
class PlattCalibrator:
    """Univariate logistic calibrator: P(y=1 | s) = 1 / (1 + exp(-(A * s + B))).

    Attributes:
        slope: Multiplier parameter A.
        intercept: Bias parameter B.
    """

    slope: float
    intercept: float

    def predict_proba(
        self,
        scores: Union[Sequence[float], Any],
    ) -> Any:
        """Calibrate continuous scores into calibrated probabilities in [0.0, 1.0]."""
        raw_list = [float(s) for s in scores]
        calibrated: list[float] = []
        for s in raw_list:
            f = self.slope * s + self.intercept
            if f >= 0:
                p = 1.0 / (1.0 + math.exp(-f))
            else:
                p = math.exp(f) / (1.0 + math.exp(f))
            calibrated.append(p)

        if NUMPY_AVAILABLE and np is not None and isinstance(scores, np.ndarray):
            return np.asarray(calibrated, dtype=np.float64)
        return calibrated

    def __call__(self, scores: Union[Sequence[float], Any]) -> Any:
        return self.predict_proba(scores)


def platt_calibrate(
    val_scores: Sequence[float] | Any,
    y_val: Sequence[int] | Any,
    test_scores: Optional[Sequence[float] | Any] = None,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Tuple[PlattCalibrator, Any, Optional[Any]]:
    """Fit Platt scaling (univariate logistic regression) strictly on validation data.

    Follows Platt's regularized targets:
        t+ = (N+ + 1) / (N+ + 2)
        t- = 1 / (N- + 2)
    Solved via Newton-Raphson optimization with backtracking line search.

    Args:
        val_scores: Uncalibrated continuous validation prediction scores/logits.
        y_val: Binary true labels (0 or 1) for the validation split.
        test_scores: Optional test split scores to transform using the fitted calibrator.
        max_iter: Maximum Newton-Raphson iterations.
        tol: Convergence tolerance for gradient norm.

    Returns:
        (fitted_calibrator, val_calibrated_probs, test_calibrated_probs)
    """
    scores_list = [float(s) for s in val_scores]
    labels_list = [int(y) for y in y_val]

    if len(scores_list) != len(labels_list):
        raise ValueError(
            f"Length mismatch: {len(scores_list)} scores vs {len(labels_list)} labels"
        )

    n = len(labels_list)
    if n == 0:
        cal = PlattCalibrator(slope=1.0, intercept=0.0)
        return cal, [], (None if test_scores is None else [])

    n_pos = sum(1 for y in labels_list if y == 1)
    n_neg = n - n_pos

    # Regularized targets per Platt (1999)
    target_pos = (n_pos + 1.0) / (n_pos + 2.0)
    target_neg = 1.0 / (n_neg + 2.0)
    targets = [target_pos if y == 1 else target_neg for y in labels_list]

    # Handle single-class degenerate cases
    if n_pos == 0:
        cal = PlattCalibrator(slope=0.0, intercept=-10.0)
        return cal, cal.predict_proba(val_scores), (cal.predict_proba(test_scores) if test_scores is not None else None)
    if n_neg == 0:
        cal = PlattCalibrator(slope=0.0, intercept=10.0)
        return cal, cal.predict_proba(val_scores), (cal.predict_proba(test_scores) if test_scores is not None else None)

    # Initial parameter guess
    A = 1.0
    B = math.log((n_pos + 1.0) / (n_neg + 1.0))

    def compute_loss(cur_a: float, cur_b: float) -> float:
        total_loss = 0.0
        for s, t in zip(scores_list, targets):
            f = cur_a * s + cur_b
            if f >= 0:
                p = 1.0 / (1.0 + math.exp(-f))
                q = math.exp(-f) / (1.0 + math.exp(-f))
            else:
                p = math.exp(f) / (1.0 + math.exp(f))
                q = 1.0 / (1.0 + math.exp(f))
            p = max(1e-15, min(1.0 - 1e-15, p))
            q = max(1e-15, min(1.0 - 1e-15, q))
            total_loss -= (t * math.log(p) + (1.0 - t) * math.log(q))
        return total_loss

    # Newton-Raphson optimization
    for _ in range(max_iter):
        grad_a = 0.0
        grad_b = 0.0
        h_aa = 0.0
        h_ab = 0.0
        h_bb = 0.0

        for s, t in zip(scores_list, targets):
            f = A * s + B
            if f >= 0:
                p = 1.0 / (1.0 + math.exp(-f))
            else:
                p = math.exp(f) / (1.0 + math.exp(f))
            p = max(1e-15, min(1.0 - 1e-15, p))
            w = p * (1.0 - p)

            diff = p - t
            grad_a += diff * s
            grad_b += diff

            h_aa += w * s * s
            h_ab += w * s
            h_bb += w

        # Numerical damping
        h_aa += 1e-4
        h_bb += 1e-4
        det = h_aa * h_bb - h_ab * h_ab

        if abs(det) < 1e-12:
            break

        delta_a = (h_bb * grad_a - h_ab * grad_b) / det
        delta_b = (-h_ab * grad_a + h_aa * grad_b) / det

        if math.sqrt(grad_a * grad_a + grad_b * grad_b) < tol:
            break

        # Backtracking line search
        step = 1.0
        cur_loss = compute_loss(A, B)
        while step > 1e-4:
            new_a = A - step * delta_a
            new_b = B - step * delta_b
            if compute_loss(new_a, new_b) < cur_loss:
                A = new_a
                B = new_b
                break
            step *= 0.5
        else:
            A = A - 1e-4 * delta_a
            B = B - 1e-4 * delta_b

    calibrator = PlattCalibrator(slope=float(A), intercept=float(B))
    val_calibrated = calibrator.predict_proba(val_scores)
    test_calibrated = calibrator.predict_proba(test_scores) if test_scores is not None else None

    return calibrator, val_calibrated, test_calibrated


# ---------------------------------------------------------------------------
# Threshold Selection Under FPR Cap (Zero Dependency)
# ---------------------------------------------------------------------------

def select_threshold_at_fpr(
    y_val: Sequence[int] | Any,
    val_scores: Sequence[float] | Any,
    target_fpr: float = 0.001,
) -> Tuple[float, float, bool]:
    """Select operating decision threshold on validation data strictly satisfying FPR <= target_fpr.

    Candidate thresholds evaluated:
        Unique values from val_scores, plus 0.0, 0.5, 1.0, and max(val_scores) + 1e-6.

    Selection & Tie-breaking rule:
        1. If feasible candidate thresholds exist (FPR <= target_fpr + 1e-12):
           - Primary: maximize TPR (Recall)
           - Secondary: minimize FPR
           - Tertiary: deterministic tie-breaking: prefer higher threshold (conservative margin)
           Returns (selected_threshold, achieved_fpr, True)
        2. If target_fpr is infeasible on validation data:
           - Primary: minimize FPR
           - Secondary: maximize TPR
           - Tertiary: deterministic tie-breaking: prefer higher threshold
           Returns (selected_threshold, achieved_fpr, False)

    Args:
        y_val: True binary labels (0 or 1).
        val_scores: Continuous probability scores or decision values.
        target_fpr: Maximum acceptable false positive rate (default 0.001 = 0.1%).

    Returns:
        Tuple: (selected_threshold, achieved_validation_fpr, is_feasible)
    """
    scores_list = [float(s) for s in val_scores]
    labels_list = [int(y) for y in y_val]

    if len(scores_list) == 0 or len(labels_list) == 0:
        return 0.5, 0.0, False

    n_neg = sum(1 for y in labels_list if y == 0)
    n_pos = sum(1 for y in labels_list if y == 1)

    if n_neg == 0:
        # No negative samples to calculate FPR; standard 0.5 threshold
        return 0.5, 0.0, True

    # Build unique candidate threshold set
    candidates = set(scores_list)
    candidates.add(0.0)
    candidates.add(0.5)
    candidates.add(1.0)
    max_score = max(scores_list)
    candidates.add(max_score + 1e-6)

    # Evaluate candidate thresholds
    # Record: (fpr, -tpr, -tau, tau, tpr)
    evaluated: list[Tuple[float, float, float, float, float]] = []

    for tau in candidates:
        fp = 0
        tp = 0
        for s, y in zip(scores_list, labels_list):
            if s >= tau:
                if y == 1:
                    tp += 1
                else:
                    fp += 1
        cur_fpr = float(fp / n_neg)
        cur_tpr = float(tp / n_pos) if n_pos > 0 else 0.0

        evaluated.append((cur_fpr, -cur_tpr, -tau, tau, cur_tpr))

    # Feasible subset: FPR <= target_fpr + 1e-12
    feasible = [item for item in evaluated if item[0] <= target_fpr + 1e-12]

    if feasible:
        # Maximize TPR (-tpr asc), minimize FPR (fpr asc), tie-break higher tau (-tau asc)
        feasible.sort(key=lambda x: (x[1], x[0], x[2]))
        best_fpr, _neg_tpr, _neg_tau, best_tau, _tpr = feasible[0]
        return float(best_tau), float(best_fpr), True
    else:
        # Minimize FPR (fpr asc), maximize TPR (-tpr asc), tie-break higher tau (-tau asc)
        evaluated.sort(key=lambda x: (x[0], x[1], x[2]))
        best_fpr, _neg_tpr, _neg_tau, best_tau, _tpr = evaluated[0]
        return float(best_tau), float(best_fpr), False


# ---------------------------------------------------------------------------
# Confusion Matrix & Binary Metrics Helpers (Zero Dependency)
# ---------------------------------------------------------------------------

def confusion_matrix_counts(
    y_true: Sequence[int] | Any,
    y_pred: Sequence[int] | Any,
) -> Tuple[int, int, int, int]:
    """Compute standard binary confusion matrix counts: (tn, fp, fn, tp).

    Definitions:
        - tn: True Negatives (y_true == 0 and y_pred == 0)
        - fp: False Positives (y_true == 0 and y_pred == 1)
        - fn: False Negatives (y_true == 1 and y_pred == 0)
        - tp: True Positives (y_true == 1 and y_pred == 1)

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).

    Returns:
        Tuple of (tn, fp, fn, tp) as native integers.
    """
    yt = [int(y) for y in y_true]
    yp = [int(y) for y in y_pred]

    if len(yt) != len(yp):
        raise ValueError(f"Length mismatch: {len(yt)} y_true vs {len(yp)} y_pred")

    tn = sum(1 for t, p in zip(yt, yp) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(yt, yp) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(yt, yp) if t == 1 and p == 0)
    tp = sum(1 for t, p in zip(yt, yp) if t == 1 and p == 1)

    return int(tn), int(fp), int(fn), int(tp)


def compute_roc_auc(
    y_true: Sequence[int] | Any,
    y_prob: Sequence[float] | Any,
) -> Optional[float]:
    """Compute exact ROC-AUC via Mann-Whitney U ranking statistic without external dependencies."""
    yt = [int(y) for y in y_true]
    yp = [float(p) for p in y_prob]

    pos_count = sum(1 for y in yt if y == 1)
    neg_count = sum(1 for y in yt if y == 0)

    if pos_count == 0 or neg_count == 0:
        return None

    paired = sorted(zip(yp, yt), key=lambda x: x[0])
    n = len(paired)
    ranks = [0.0] * n

    i = 0
    while i < n:
        j = i
        while j < n and paired[j][0] == paired[i][0]:
            j += 1
        rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = rank
        i = j

    pos_rank_sum = sum(ranks[k] for k in range(n) if paired[k][1] == 1)
    u = pos_rank_sum - (pos_count * (pos_count + 1)) / 2.0
    return float(u / (pos_count * neg_count))


def compute_pr_auc(
    y_true: Sequence[int] | Any,
    y_prob: Sequence[float] | Any,
) -> Optional[float]:
    """Compute exact Average Precision (PR-AUC) without external dependencies."""
    yt = [int(y) for y in y_true]
    yp = [float(p) for p in y_prob]

    pos_count = sum(1 for y in yt if y == 1)
    if pos_count == 0:
        return None

    neg_count = sum(1 for y in yt if y == 0)
    if neg_count == 0:
        return 1.0

    paired = sorted(zip(yp, yt), key=lambda x: x[0], reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    ap = 0.0
    n = len(paired)

    i = 0
    while i < n:
        j = i
        while j < n and paired[j][0] == paired[i][0]:
            if paired[j][1] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        recall = tp / pos_count
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        ap += (recall - prev_recall) * precision
        prev_recall = recall
        i = j

    return float(ap)


def binary_metrics(
    y_true: Sequence[int] | Any,
    y_pred: Sequence[int] | Any,
    y_prob: Optional[Sequence[float] | Any] = None,
) -> dict[str, Any]:
    """Compute comprehensive binary classification metrics and confusion counts.

    Metrics computed:
        - tn, fp, fn, tp, total
        - accuracy: (tp + tn) / total
        - precision: tp / (tp + fp)
        - recall / tpr: tp / (tp + fn)
        - specificity / tnr: tn / (tn + fp)
        - fpr: fp / (fp + tn)
        - fnr: fn / (fn + tp)
        - f1: 2 * precision * recall / (precision + recall)
        - balanced_accuracy: 0.5 * (recall + specificity)
        - roc_auc: Area Under the ROC Curve (if y_prob provided, else None)
        - pr_auc: Area Under the Precision-Recall Curve (if y_prob provided, else None)

    Args:
        y_true: True binary labels (0 or 1).
        y_pred: Predicted binary labels (0 or 1).
        y_prob: Optional continuous prediction probabilities.

    Returns:
        Dictionary mapping metric names to native float/int values.
    """
    tn, fp, fn, tp = confusion_matrix_counts(y_true, y_pred)
    total = tn + fp + fn + tp

    accuracy = float((tp + tn) / total) if total > 0 else 0.0
    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
    specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = float(fn / (fn + tp)) if (fn + tp) > 0 else 0.0

    if precision + recall > 0.0:
        f1 = float(2.0 * precision * recall / (precision + recall))
    else:
        f1 = 0.0

    balanced_accuracy = float(0.5 * (recall + specificity))

    roc_auc_val: Optional[float] = None
    pr_auc_val: Optional[float] = None

    if y_prob is not None:
        roc_auc_val = compute_roc_auc(y_true, y_prob)
        pr_auc_val = compute_pr_auc(y_true, y_prob)

    return {
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "total": total,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "fpr": fpr,
        "fnr": fnr,
        "f1": f1,
        "balanced_accuracy": balanced_accuracy,
        "roc_auc": roc_auc_val,
        "pr_auc": pr_auc_val,
    }


__all__ = [
    "PADDING_VECTOR",
    "PaperReferenceLSTMModel",
    "ImprovedMaskedBiGRUModel",
    "PlattCalibrator",
    "is_torch_available",
    "require_torch",
    "create_paper_model",
    "create_improved_model",
    "get_paper_model_dimensions",
    "get_improved_model_dimensions",
    "set_deterministic_seed",
    "configure_bce_loss",
    "fit_model",
    "predict_probabilities",
    "platt_calibrate",
    "select_threshold_at_fpr",
    "confusion_matrix_counts",
    "compute_roc_auc",
    "compute_pr_auc",
    "binary_metrics",
]
