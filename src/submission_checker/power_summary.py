# SPDX-FileCopyrightText: Copyright (c) 2024 MLCommons
# SPDX-License-Identifier: Apache-2.0
"""One point's power figures, for storing beside the run rather than checking it.

The checker computes a point's provisioned and per-point power to *verify* what the
submitter wrote. Consumers of the results — the database, the visualizer — want the
same figures as data: provisioned power, the power the point engages, throughput per
kilowatt, and whether any value fell back to an Appendix D default ("MLC Estimated
Power"). :func:`derive_point_power` produces them with the checker's own arithmetic
(:meth:`SystemPower.compute` and :meth:`PowerComputation.point_power_kw`), so a stored
figure can never disagree with what compliance accepted.

It works on parsed file contents, not paths, because its callers hold them already:
``runs create`` from the run folder, and the review-repo sync job from a PR's files.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models.file.system_power import PowerComputation, SystemPower

__all__ = ["derive_point_power", "host_cores_by_ensemble"]

_NS_PER_S = 1e9


def host_cores_by_ensemble(system_desc: dict[str, Any]) -> dict[int, int]:
    """``host_processor_core_count`` per ``system_node_ensemble_id``, for D.2's default.

    Read from §8.2.1's ``node_types``; an ensemble id given as a digit string is
    coerced, as :class:`~submission_checker.models.NodeType` does.
    """
    cores: dict[int, int] = {}
    for node in system_desc.get("node_types") or []:
        if not isinstance(node, dict):
            continue
        ensemble = node.get("system_node_ensemble_id")
        if isinstance(ensemble, str) and ensemble.strip().isdigit():
            ensemble = int(ensemble)
        count = node.get("host_processor_core_count")
        if isinstance(ensemble, int) and isinstance(count, int):
            cores[ensemble] = count
    return cores


def _system_tps(result_summary: dict[str, Any]) -> float | None:
    """``total output tokens / elapsed seconds``, as ``PointSummary.system_tps``."""
    lengths = result_summary.get("output_sequence_lengths")
    duration = _number(result_summary.get("duration_ns"))
    total = _number(lengths.get("total")) if isinstance(lengths, dict) else None
    if duration is None or total is None or duration <= 0:
        return None
    return total / (duration / _NS_PER_S)


def _number(value: object) -> float | None:
    """A JSON number as float; ``None`` for bools and anything non-numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _nodes_by_set(point_config: dict[str, Any], power: PowerComputation) -> dict[int, int] | None:
    """The point's ``nodes_used`` keyed by ``node_set_id``, or ``None`` if unusable.

    An absent declaration is ``{}`` — every set fully engaged, §4.5.3's default. One
    that names an ensemble no single set matches, or more nodes than are provisioned,
    is the error the checker's ``nodes-used`` rule reports; no figure is derived from
    it rather than guess.
    """
    declared = point_config.get("nodes_used")
    if declared is None:
        return {}
    if not isinstance(declared, list):
        return None
    by_set: dict[int, int] = {}
    for entry in declared:
        if not isinstance(entry, dict):
            return None
        ensemble, nodes = entry.get("system_node_ensemble_id"), entry.get("nodes")
        matches = [s for s in power.sets if s.system_node_ensemble_id == ensemble]
        if len(matches) != 1 or not isinstance(nodes, int):
            return None
        node_set = matches[0]
        if not 1 <= nodes <= node_set.nodes_provisioned or node_set.node_set_id in by_set:
            return None
        by_set[node_set.node_set_id] = nodes
    return by_set


def derive_point_power(
    system_power: dict[str, Any],
    point_config: dict[str, Any],
    system_desc: dict[str, Any],
    result_summary: dict[str, Any],
) -> dict[str, Any]:
    """Power figures for one point, as a JSON-ready mapping.

    Args:
        system_power: The system's ``system_power.json``.
        point_config: The point's ``point.yaml``.
        system_desc: The point's ``system_desc.json`` (for D.2's core counts).
        result_summary: The point's ``performance/result_summary.json``.

    Returns:
        ``provisioned_power_kw``, ``point_power_kw`` and ``system_tps_per_kw`` (each
        ``None`` where it cannot be determined), ``mlc_estimated_power``, and the
        ``estimated`` values and ``problems`` behind them. Never raises on bad input:
        a descriptor the checker would reject yields ``None`` figures and says why.
    """
    out: dict[str, Any] = {
        "provisioned_power_kw": None,
        "point_power_kw": None,
        "system_tps_per_kw": None,
        "mlc_estimated_power": False,
        "estimated": [],
        "problems": [],
    }
    try:
        model = SystemPower.model_validate(system_power)
    except ValidationError as exc:
        out["problems"] = [f"system_power.json is invalid: {exc.error_count()} error(s)"]
        return out

    power = model.compute(host_cores_by_ensemble(system_desc))
    out["provisioned_power_kw"] = power.provisioned_power_kw
    out["estimated"] = list(power.estimated)
    out["problems"] = list(power.problems)
    # The submitter may also declare the tag outright (Appendix E's own field).
    out["mlc_estimated_power"] = bool(power.estimated) or model.mlc_estimated_power is True
    if power.provisioned_power_kw is None:
        return out

    nodes = _nodes_by_set(point_config, power)
    if nodes is None:
        out["problems"].append("nodes_used does not match the power descriptor's node sets")
        return out
    point_kw = power.point_power_kw(nodes)
    out["point_power_kw"] = point_kw

    tps = _system_tps(result_summary)
    if point_kw and tps is not None:
        # §4.5.2 reports it to one decimal place.
        out["system_tps_per_kw"] = round(tps / point_kw, 1)
    return out
