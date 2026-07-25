from __future__ import annotations

import math
from typing import Any

import torch


ACTION_Q_RESIDUAL_DUELING_ARCHITECTURE = "state_action_dueling_v1"
ACTION_Q_RESIDUAL_MLP_ARCHITECTURE = "state_action_mlp_v2"
ACTION_Q_RESIDUAL_LEGAL_SET_CONTEXT_ARCHITECTURE = "state_action_legal_set_context_v1"
ACTION_Q_RESIDUAL_FULL_CROSS_ARCHITECTURE = "state_action_full_cross_v1"
ACTION_Q_RESIDUAL_PAIRWISE_LEGAL_SET_ARCHITECTURE = "state_action_pairwise_legal_set_v1"


class ActionQResidualDuelingCritic(torch.nn.Module):
    def __init__(self, *, state_dim: int, action_dim: int, rank: int) -> None:
        super().__init__()
        self.architecture = ACTION_Q_RESIDUAL_DUELING_ARCHITECTURE
        self.state_model = torch.nn.Linear(int(state_dim), int(rank))
        self.action_model = torch.nn.Linear(int(action_dim), int(rank), bias=False)
        self.output_weight = torch.nn.Parameter(torch.ones(int(rank), dtype=torch.float32))

    def forward(self, state_features: Any, action_features: Any) -> Any:
        state_h = torch.tanh(self.state_model(state_features))
        action_h = torch.tanh(self.action_model(action_features))
        if len(action_h.shape) == 3 and len(state_h.shape) == 2:
            state_h = state_h[:, None, :].expand(-1, action_h.shape[1], -1)
        scale = 1.0 / math.sqrt(max(1, int(self.output_weight.numel())))
        return (state_h * action_h * self.output_weight).sum(dim=-1) * float(scale)


class ActionQResidualFullCrossCritic(torch.nn.Module):
    def __init__(self, *, state_dim: int, action_dim: int, rank: int) -> None:
        super().__init__()
        self.architecture = ACTION_Q_RESIDUAL_FULL_CROSS_ARCHITECTURE
        self.state_model = torch.nn.Linear(int(state_dim), int(rank))
        self.action_model = torch.nn.Linear(int(action_dim), int(rank), bias=False)
        self.output_weight = torch.nn.Parameter(torch.empty(int(rank) * int(rank), dtype=torch.float32))
        with torch.no_grad():
            scale = 1.0 / math.sqrt(max(1, int(self.output_weight.numel())))
            self.output_weight.uniform_(-scale, scale)

    def forward(self, state_features: Any, action_features: Any) -> Any:
        state_h = torch.tanh(self.state_model(state_features))
        action_h = torch.tanh(self.action_model(action_features))
        if len(action_h.shape) == 3 and len(state_h.shape) == 2:
            state_h = state_h[:, None, :].expand(-1, action_h.shape[1], -1)
        cross = state_h[..., :, None] * action_h[..., None, :]
        cross = cross.reshape(*cross.shape[:-2], -1)
        scale = 1.0 / math.sqrt(max(1, int(self.output_weight.numel())))
        return (cross * self.output_weight).sum(dim=-1) * float(scale)


class ActionQResidualMlpCritic(torch.nn.Module):
    def __init__(self, *, state_dim: int, action_dim: int, rank: int) -> None:
        super().__init__()
        self.architecture = ACTION_Q_RESIDUAL_MLP_ARCHITECTURE
        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)
        self.rank = int(rank)
        self.input_model = torch.nn.Linear(self.state_dim + self.action_dim, self.rank)
        self.output_model = torch.nn.Linear(self.rank, 1)

    def forward(self, state_features: Any, action_features: Any) -> Any:
        if len(action_features.shape) == 3 and len(state_features.shape) == 2:
            state_features = state_features[:, None, :].expand(-1, action_features.shape[1], -1)
        state_action = torch.cat([state_features, action_features], dim=-1)
        hidden = torch.tanh(self.input_model(state_action))
        return self.output_model(hidden).squeeze(-1)


class ActionQResidualLegalSetContextCritic(torch.nn.Module):
    def __init__(self, *, state_dim: int, action_dim: int, rank: int) -> None:
        super().__init__()
        self.architecture = ACTION_Q_RESIDUAL_LEGAL_SET_CONTEXT_ARCHITECTURE
        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)
        self.rank = int(rank)
        self.state_model = torch.nn.Linear(self.state_dim, self.rank)
        self.action_model = torch.nn.Linear(self.action_dim, self.rank, bias=False)
        self.context_model = torch.nn.Linear(self.output_dim(self.rank), self.rank, bias=False)
        self.output_weight = torch.nn.Parameter(torch.zeros(self.rank, dtype=torch.float32))
        self.output_bias = torch.nn.Parameter(torch.zeros((), dtype=torch.float32))
        with torch.no_grad():
            scale = 1.0 / math.sqrt(max(1, int(self.output_weight.numel())))
            self.output_weight.uniform_(-scale, scale)

    @staticmethod
    def output_dim(rank: int) -> int:
        return int(6 * int(rank) + 4)

    def forward(
        self,
        state_features: Any,
        action_features: Any,
        *,
        local_rows: Any | None = None,
        row_count: int | None = None,
        counts: Any | None = None,
        broad_prior: Any | None = None,
        mask: Any | None = None,
    ) -> Any:
        state_h = torch.tanh(self.state_model(state_features))
        action_h = torch.tanh(self.action_model(action_features))
        if broad_prior is None:
            broad_prior = torch.zeros(action_h.shape[:-1], dtype=action_h.dtype, device=action_h.device)
        else:
            broad_prior = broad_prior.to(dtype=action_h.dtype, device=action_h.device)

        if len(action_h.shape) == 3:
            if len(state_h.shape) == 2:
                state_h = state_h[:, None, :].expand(-1, action_h.shape[1], -1)
            legal_mask = (
                mask.to(dtype=torch.bool, device=action_h.device)
                if mask is not None
                else torch.ones(action_h.shape[:-1], dtype=torch.bool, device=action_h.device)
            )
            legal_counts = legal_mask.sum(dim=1).clamp_min(1).to(dtype=action_h.dtype)
            masked_action_h = action_h.masked_fill(~legal_mask[..., None], 0.0)
            mean_action = masked_action_h.sum(dim=1) / legal_counts[:, None]
            max_action = action_h.masked_fill(~legal_mask[..., None], -1.0e9).max(dim=1).values
            broad_masked = broad_prior.masked_fill(~legal_mask, 0.0)
            mean_broad = broad_masked.sum(dim=1) / legal_counts
            max_broad = broad_prior.masked_fill(~legal_mask, -1.0e9).max(dim=1).values
            count_feature = torch.log1p(legal_counts) / math.log(64.0)
            row_mean_action = mean_action[:, None, :].expand_as(action_h)
            row_max_action = max_action[:, None, :].expand_as(action_h)
            row_mean_broad = mean_broad[:, None]
            row_max_broad = max_broad[:, None]
            row_count_feature = count_feature[:, None]
            features = torch.cat(
                [
                    state_h,
                    action_h,
                    state_h * action_h,
                    action_h - row_mean_action,
                    (broad_prior - row_mean_broad)[..., None],
                    row_mean_action,
                    row_max_action,
                    row_mean_broad[..., None].expand(*action_h.shape[:-1], 1),
                    row_max_broad[..., None].expand(*action_h.shape[:-1], 1),
                    row_count_feature[..., None].expand(*action_h.shape[:-1], 1),
                ],
                dim=-1,
            )
            hidden = torch.tanh(self.context_model(features))
            return (hidden * self.output_weight).sum(dim=-1) + self.output_bias

        if local_rows is None:
            local_rows = torch.zeros((int(action_h.shape[0]),), dtype=torch.long, device=action_h.device)
            row_count = 1
        local_rows = local_rows.to(dtype=torch.long, device=action_h.device)
        if row_count is None:
            row_count = int(local_rows.max().detach().cpu().item()) + 1 if int(local_rows.numel()) else 0
        if counts is None:
            counts = torch.zeros((int(row_count),), dtype=action_h.dtype, device=action_h.device)
            counts.scatter_add_(0, local_rows, torch.ones((int(action_h.shape[0]),), dtype=action_h.dtype, device=action_h.device))
        counts = counts.to(dtype=action_h.dtype, device=action_h.device).clamp_min(1.0)
        action_sum = torch.zeros((int(row_count), int(self.rank)), dtype=action_h.dtype, device=action_h.device)
        action_sum.scatter_add_(0, local_rows[:, None].expand(-1, int(self.rank)), action_h)
        mean_action = action_sum / counts[:, None]
        max_action = torch.full((int(row_count), int(self.rank)), -1.0e9, dtype=action_h.dtype, device=action_h.device)
        max_action.scatter_reduce_(0, local_rows[:, None].expand(-1, int(self.rank)), action_h, reduce="amax", include_self=True)
        broad_sum = torch.zeros((int(row_count),), dtype=action_h.dtype, device=action_h.device)
        broad_sum.scatter_add_(0, local_rows, broad_prior)
        mean_broad = broad_sum / counts
        max_broad = torch.full((int(row_count),), -1.0e9, dtype=action_h.dtype, device=action_h.device)
        max_broad.scatter_reduce_(0, local_rows, broad_prior, reduce="amax", include_self=True)
        count_feature = torch.log1p(counts) / math.log(64.0)
        row_mean_action = mean_action[local_rows]
        row_max_action = max_action[local_rows]
        row_mean_broad = mean_broad[local_rows]
        row_max_broad = max_broad[local_rows]
        row_count_feature = count_feature[local_rows]
        features = torch.cat(
            [
                state_h,
                action_h,
                state_h * action_h,
                action_h - row_mean_action,
                (broad_prior - row_mean_broad)[:, None],
                row_mean_action,
                row_max_action,
                row_mean_broad[:, None],
                row_max_broad[:, None],
                row_count_feature[:, None],
            ],
            dim=-1,
        )
        hidden = torch.tanh(self.context_model(features))
        return (hidden * self.output_weight).sum(dim=-1) + self.output_bias


class ActionQResidualPairwiseLegalSetCritic(torch.nn.Module):
    def __init__(self, *, state_dim: int, action_dim: int, rank: int) -> None:
        super().__init__()
        self.architecture = ACTION_Q_RESIDUAL_PAIRWISE_LEGAL_SET_ARCHITECTURE
        self.state_dim = int(state_dim)
        self.action_dim = int(action_dim)
        self.rank = int(rank)
        self.state_model = torch.nn.Linear(self.state_dim, self.rank)
        self.action_model = torch.nn.Linear(self.action_dim, self.rank, bias=False)
        self.context_model = torch.nn.Linear(self.output_dim(self.rank), self.rank, bias=False)
        self.output_weight = torch.nn.Parameter(torch.zeros(self.rank, dtype=torch.float32))
        self.output_bias = torch.nn.Parameter(torch.zeros((), dtype=torch.float32))
        with torch.no_grad():
            scale = 1.0 / math.sqrt(max(1, int(self.output_weight.numel())))
            self.output_weight.uniform_(-scale, scale)

    @staticmethod
    def output_dim(rank: int) -> int:
        return int(8 * int(rank) + 5)

    def forward(
        self,
        state_features: Any,
        action_features: Any,
        *,
        local_rows: Any | None = None,
        row_count: int | None = None,
        counts: Any | None = None,
        broad_prior: Any | None = None,
        mask: Any | None = None,
    ) -> Any:
        state_h = torch.tanh(self.state_model(state_features))
        action_h = torch.tanh(self.action_model(action_features))
        if broad_prior is None:
            broad_prior = torch.zeros(action_h.shape[:-1], dtype=action_h.dtype, device=action_h.device)
        else:
            broad_prior = broad_prior.to(dtype=action_h.dtype, device=action_h.device)

        if len(action_h.shape) == 3:
            if len(state_h.shape) == 2:
                state_h = state_h[:, None, :].expand(-1, action_h.shape[1], -1)
            legal_mask = (
                mask.to(dtype=torch.bool, device=action_h.device)
                if mask is not None
                else torch.ones(action_h.shape[:-1], dtype=torch.bool, device=action_h.device)
            )
            legal_counts = legal_mask.sum(dim=1).clamp_min(1).to(dtype=action_h.dtype)
            competitor_counts = (legal_counts - 1.0).clamp_min(1.0)
            masked_action_h = action_h.masked_fill(~legal_mask[..., None], 0.0)
            action_sum = masked_action_h.sum(dim=1)
            mean_action = action_sum / legal_counts[:, None]
            max_action = action_h.masked_fill(~legal_mask[..., None], -1.0e9).max(dim=1).values
            other_mean_action = (action_sum[:, None, :] - action_h) / competitor_counts[:, None, None]
            other_mean_action = torch.where(
                (legal_counts > 1.0)[:, None, None],
                other_mean_action,
                action_h,
            )
            pair_mean_delta = action_h - other_mean_action
            pair_mask = (
                legal_mask[:, :, None]
                & legal_mask[:, None, :]
                & ~torch.eye(int(action_h.shape[1]), dtype=torch.bool, device=action_h.device)[None, :, :]
            )
            pair_abs_mean_delta = (
                (action_h[:, :, None, :] - action_h[:, None, :, :]).abs()
                .masked_fill(~pair_mask[..., None], 0.0)
                .sum(dim=2)
                / competitor_counts[:, None, None]
            )
            pair_abs_mean_delta = torch.where(
                (legal_counts > 1.0)[:, None, None],
                pair_abs_mean_delta,
                torch.zeros_like(pair_abs_mean_delta),
            )
            broad_masked = broad_prior.masked_fill(~legal_mask, 0.0)
            broad_sum = broad_masked.sum(dim=1)
            mean_broad = broad_sum / legal_counts
            max_broad = broad_prior.masked_fill(~legal_mask, -1.0e9).max(dim=1).values
            min_broad = broad_prior.masked_fill(~legal_mask, 1.0e9).min(dim=1).values
            other_mean_broad = (broad_sum[:, None] - broad_prior) / competitor_counts[:, None]
            other_mean_broad = torch.where((legal_counts > 1.0)[:, None], other_mean_broad, broad_prior)
            count_feature = torch.log1p(legal_counts) / math.log(64.0)
            competitor_count_feature = torch.log1p((legal_counts - 1.0).clamp_min(0.0)) / math.log(64.0)
            features = torch.cat(
                [
                    state_h,
                    action_h,
                    state_h * action_h,
                    action_h - mean_action[:, None, :],
                    mean_action[:, None, :].expand_as(action_h),
                    max_action[:, None, :].expand_as(action_h),
                    pair_mean_delta,
                    pair_abs_mean_delta,
                    (broad_prior - other_mean_broad)[..., None],
                    (max_broad[:, None] - broad_prior)[..., None],
                    (broad_prior - min_broad[:, None])[..., None],
                    count_feature[:, None, None].expand(*action_h.shape[:-1], 1),
                    competitor_count_feature[:, None, None].expand(*action_h.shape[:-1], 1),
                ],
                dim=-1,
            )
            hidden = torch.tanh(self.context_model(features))
            return (hidden * self.output_weight).sum(dim=-1) + self.output_bias

        if local_rows is None:
            local_rows = torch.zeros((int(action_h.shape[0]),), dtype=torch.long, device=action_h.device)
            row_count = 1
        local_rows = local_rows.to(dtype=torch.long, device=action_h.device)
        if row_count is None:
            row_count = int(local_rows.max().detach().cpu().item()) + 1 if int(local_rows.numel()) else 0
        if counts is None:
            counts = torch.zeros((int(row_count),), dtype=action_h.dtype, device=action_h.device)
            counts.scatter_add_(0, local_rows, torch.ones((int(action_h.shape[0]),), dtype=action_h.dtype, device=action_h.device))
        counts = counts.to(dtype=action_h.dtype, device=action_h.device).clamp_min(1.0)
        action_sum = torch.zeros((int(row_count), int(self.rank)), dtype=action_h.dtype, device=action_h.device)
        action_sum.scatter_add_(0, local_rows[:, None].expand(-1, int(self.rank)), action_h)
        mean_action = action_sum / counts[:, None]
        max_action = torch.full((int(row_count), int(self.rank)), -1.0e9, dtype=action_h.dtype, device=action_h.device)
        max_action.scatter_reduce_(0, local_rows[:, None].expand(-1, int(self.rank)), action_h, reduce="amax", include_self=True)
        competitor_counts = (counts - 1.0).clamp_min(1.0)
        other_mean_action = (action_sum[local_rows] - action_h) / competitor_counts[local_rows, None]
        other_mean_action = torch.where((counts[local_rows] > 1.0)[:, None], other_mean_action, action_h)
        pair_mean_delta = action_h - other_mean_action
        pair_abs_mean_delta = torch.zeros_like(action_h)
        for row in range(int(row_count)):
            row_mask = local_rows == int(row)
            if int(row_mask.sum().detach().cpu().item()) <= 1:
                continue
            row_actions = action_h[row_mask]
            pair_abs_mean_delta[row_mask] = (row_actions[:, None, :] - row_actions[None, :, :]).abs().sum(dim=1) / float(
                max(1, int(row_actions.shape[0]) - 1)
            )
        broad_sum = torch.zeros((int(row_count),), dtype=action_h.dtype, device=action_h.device)
        broad_sum.scatter_add_(0, local_rows, broad_prior)
        mean_broad = broad_sum / counts
        max_broad = torch.full((int(row_count),), -1.0e9, dtype=action_h.dtype, device=action_h.device)
        max_broad.scatter_reduce_(0, local_rows, broad_prior, reduce="amax", include_self=True)
        min_broad = torch.full((int(row_count),), 1.0e9, dtype=action_h.dtype, device=action_h.device)
        min_broad.scatter_reduce_(0, local_rows, broad_prior, reduce="amin", include_self=True)
        other_mean_broad = (broad_sum[local_rows] - broad_prior) / competitor_counts[local_rows]
        other_mean_broad = torch.where(counts[local_rows] > 1.0, other_mean_broad, broad_prior)
        count_feature = torch.log1p(counts) / math.log(64.0)
        competitor_count_feature = torch.log1p((counts - 1.0).clamp_min(0.0)) / math.log(64.0)
        features = torch.cat(
            [
                state_h,
                action_h,
                state_h * action_h,
                action_h - mean_action[local_rows],
                mean_action[local_rows],
                max_action[local_rows],
                pair_mean_delta,
                pair_abs_mean_delta,
                (broad_prior - other_mean_broad)[:, None],
                (max_broad[local_rows] - broad_prior)[:, None],
                (broad_prior - min_broad[local_rows])[:, None],
                count_feature[local_rows, None],
                competitor_count_feature[local_rows, None],
            ],
            dim=-1,
        )
        hidden = torch.tanh(self.context_model(features))
        return (hidden * self.output_weight).sum(dim=-1) + self.output_bias
