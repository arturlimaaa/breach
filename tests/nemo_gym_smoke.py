"""NeMo Gym loads breach.gym's environment and breach.export's rollouts. Not part of the core gate: it needs nemo-gym,
which needs Python 3.13.14 or later. From the repository root:

    python3 -m venv <venv>
    <venv>/bin/pip install nemo-gym==0.7.0 setuptools==80.10.2
    <venv>/bin/python -m unittest tests.nemo_gym_smoke

hydra-core imports pkg_resources, which a fresh venv lacks; NeMo Gym's own lockfile pins setuptools 80.10.2.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from omegaconf import OmegaConf

from breach.export import export
from breach.gym import BreachGym, row
from nemo_gym.base_resources_server import BaseResourcesServerConfig, BaseVerifyResponse
from nemo_gym.config_types import BaseServerConfig
from nemo_gym.openai_utils import NeMoGymResponse
from nemo_gym.server_utils import ServerClient
from resources_servers.gymnasium import EnvResetResponse, EnvStepResponse
from tests.test_export import COUNT_HC, COUNT_LOGS, PROMPT, REPLY, call, failed
from tests.test_proof import write_run

STICK_2 = {"planks": -2, "stick": 2}


def responding(*calls):
    """A policy response holding these `act` calls, as NeMo Gym's model servers return it."""
    return NeMoGymResponse(
        id="resp_0", created_at=0.0, model="policy", object="response", parallel_tool_calls=True, tool_choice="auto", tools=[],
        output=[{"type": "function_call", "call_id": f"call_{n}", "name": "act", "arguments": json.dumps(c)} for n, c in enumerate(calls)],
    )


class NeMoGymSmokeTests(unittest.TestCase):
    def test_reset_and_step_as_gymnasium_agent_sends_them_pay_the_revision_and_the_goal(self):
        server = BreachGym(
            config=BaseResourcesServerConfig(host="127.0.0.1", port=0, entrypoint="", name="breach"),
            server_client=ServerClient(head_server_config=BaseServerConfig(host="127.0.0.1", port=0), global_config_dict=OmegaConf.create({})),
        )
        client = TestClient(server.setup_webserver())
        dataset_row = row("stick-count-2", "stick", seed=1, inventory={"planks": 2})
        reset = client.post("/reset", json=dataset_row)
        craft = {"action": "craft", "target": "stick", "predicted": STICK_2}
        step = client.post("/step", json={**dataset_row, "response": responding(craft).model_dump(mode="json")})
        observation = json.loads(EnvResetResponse.model_validate(reset.json()).observation)
        stepped = EnvStepResponse.model_validate(step.json())
        [output] = stepped.info["tool_outputs"]
        self.assertEqual(
            (reset.status_code, observation["inventory"], step.status_code, stepped.reward, stepped.terminated, stepped.truncated,
             output["call_id"], json.loads(output["output"])["observed"]),
            (200, {"planks": 2}, 200, 2.0, True, False, "call_0", STICK_2),
        )

    def test_every_exported_rollout_loads_as_a_nemo_gym_verify_response(self):
        calls = [call(COUNT_HC["id"], 2, reasoning="Two sticks came out."), failed(COUNT_HC["id"], 2)]
        with tempfile.TemporaryDirectory() as tmp:
            lines = [json.dumps(r) for r in export(write_run(Path(tmp) / "run", "D", [COUNT_HC], COUNT_LOGS, calls))]
        loaded = [BaseVerifyResponse.model_validate_json(line) for line in lines]
        self.assertEqual(
            [(v.reward, v.mask_sample, [m.content for m in v.responses_create_params.input], [o.type for o in v.response.output],
              v.response.output_text) for v in loaded],
            [
                (0.0, False, [PROMPT[0]["content"]], ["reasoning", "message"], REPLY),
                (0.0, True, [PROMPT[0]["content"]], [], ""),
            ],
        )


if __name__ == "__main__":
    unittest.main()
