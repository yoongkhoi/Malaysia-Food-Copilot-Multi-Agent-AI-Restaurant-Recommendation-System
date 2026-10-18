"""Keep the default test process on the deterministic graph.

The running application defaults ENABLE_AGENT_WORKFLOW to on.
Tests call the multi-agent workflow directly when they need it.
"""

import os

os.environ["ENABLE_AGENT_WORKFLOW"] = "false"
