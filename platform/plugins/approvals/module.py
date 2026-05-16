from plugins.approvals.policy import AutomationPolicyEngine
from plugins.approvals.approval_queue import ApprovalQueue

class ApprovalFirstAutomation:
    def __init__(self) -> None:
        self.policies = AutomationPolicyEngine()
        self.queue = ApprovalQueue()

def create_plugin():
    return ApprovalFirstAutomation()
