# SPDX-FileCopyrightText: Copyright (c) 2024 MLCommons
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for submission_checker.power_summary."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from submission_checker.power_summary import derive_point_power, host_cores_by_ensemble

_SOURCE = {"source_type": "vendor_spec", "source": "https://example.com/x"}


def _power(nodes: int = 2, **extra: Any) -> dict[str, Any]:
    """A two-node air-cooled descriptor: 9.8 kW major per node, 14.7 kW with overhead."""
    return {
        "system_desc_id": "sys",
        "cooling": "air",
        "node_sets": [
            {
                "node_set_id": 0,
                "system_node_ensemble_id": 0,
                "nodes_provisioned": nodes,
                "power_method": "component_sum",
                "components": {
                    "cpu": {"count_per_node": 2, "tdp_per_unit": {"value_w": 350, **_SOURCE}},
                    "accelerator": {
                        "count_per_node": 8,
                        "tdp_per_unit": {"value_w": 700, **_SOURCE},
                    },
                    "scale_up_network": {
                        "method": "declared_tdp",
                        "switch_count": 1,
                        "tdp_per_switch": {"value_w": 3500, **_SOURCE},
                    },
                },
            }
        ],
        "scale_out": {"present": False},
        **extra,
    }


#: 29.4 kW provisioned / 14.7 kW for one of two nodes; 2940 tokens/s.
_SUMMARY = {"duration_ns": 10 * 10**9, "output_sequence_lengths": {"total": 29_400}}


@pytest.mark.unit
class TestDerivePointPower:
    def test_fully_engaged_point(self) -> None:
        out = derive_point_power(_power(), {}, {}, _SUMMARY)
        assert out["provisioned_power_kw"] == 29.4
        assert out["point_power_kw"] == 29.4
        assert out["system_tps_per_kw"] == 100.0
        assert out["mlc_estimated_power"] is False
        assert out["problems"] == []

    def test_point_scaled_by_nodes_used(self) -> None:
        point = {"nodes_used": [{"system_node_ensemble_id": 0, "nodes": 1}]}
        out = derive_point_power(_power(), point, {}, _SUMMARY)
        assert out["provisioned_power_kw"] == 29.4
        assert out["point_power_kw"] == 14.7
        assert out["system_tps_per_kw"] == 200.0

    def test_appendix_d_default_sets_the_estimated_flag(self) -> None:
        power = _power()
        cpu = power["node_sets"][0]["components"]["cpu"]
        cpu["tdp_per_unit"] = {"value_w": 350, "source_type": "mlc_default", "source": "D.2"}
        out = derive_point_power(power, {}, {}, _SUMMARY)
        assert out["mlc_estimated_power"] is True
        assert out["estimated"]

    def test_submitter_declared_estimate_is_kept(self) -> None:
        out = derive_point_power(_power(mlc_estimated_power=True), {}, {}, _SUMMARY)
        assert out["mlc_estimated_power"] is True

    def test_nodes_used_beyond_provisioned_derives_no_point_figure(self) -> None:
        point = {"nodes_used": [{"system_node_ensemble_id": 0, "nodes": 3}]}
        out = derive_point_power(_power(), point, {}, _SUMMARY)
        assert out["provisioned_power_kw"] == 29.4
        assert out["point_power_kw"] is None
        assert out["system_tps_per_kw"] is None
        assert out["problems"]

    def test_unknown_ensemble_derives_no_point_figure(self) -> None:
        point = {"nodes_used": [{"system_node_ensemble_id": 7, "nodes": 1}]}
        out = derive_point_power(_power(), point, {}, _SUMMARY)
        assert out["point_power_kw"] is None

    def test_invalid_descriptor_never_raises(self) -> None:
        out = derive_point_power({"cooling": "steam"}, {}, {}, _SUMMARY)
        assert out["provisioned_power_kw"] is None
        assert out["problems"]

    def test_missing_throughput_leaves_tps_per_kw_unset(self) -> None:
        out = derive_point_power(_power(), {}, {}, {})
        assert out["point_power_kw"] == 29.4
        assert out["system_tps_per_kw"] is None

    def test_inputs_not_mutated(self) -> None:
        power = _power()
        before = copy.deepcopy(power)
        derive_point_power(power, {}, {}, _SUMMARY)
        assert power == before


@pytest.mark.unit
class TestHostCoresByEnsemble:
    def test_reads_node_types_and_coerces_ids(self) -> None:
        desc = {
            "node_types": [
                {"system_node_ensemble_id": "0", "host_processor_core_count": 64},
                {"system_node_ensemble_id": 1, "host_processor_core_count": 32},
                {"system_node_ensemble_id": 2},
                "junk",
            ]
        }
        assert host_cores_by_ensemble(desc) == {0: 64, 1: 32}
