import unittest

from q3_agent_runtime_tests.src.runtime import AgentRuntimeSimulator, BranchStatus, GraphDefinition


class AgentRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = AgentRuntimeSimulator()
        self.runtime.activate_graph("tenant-a", GraphDefinition("support-agent", 7, ("crm", "order")))

    def test_pinned_run_does_not_move_to_new_active_graph(self) -> None:
        run = self.runtime.start_run("tenant-a", "run-001")
        self.runtime.activate_graph("tenant-a", GraphDefinition("support-agent", 8, ("crm", "order", "billing")))
        resumed = self.runtime.resume_run("tenant-a", "run-001")
        self.assertEqual(resumed.graph_ref, "support-agent@v7")
        self.assertEqual(run.graph_ref, resumed.graph_ref)

    def test_new_run_uses_new_active_graph_without_rewriting_old_run(self) -> None:
        old = self.runtime.start_run("tenant-a", "run-001")
        self.runtime.activate_graph("tenant-a", GraphDefinition("support-agent", 8, ("crm", "order", "billing")))
        new = self.runtime.start_run("tenant-a", "run-002")
        self.assertEqual(old.graph_ref, "support-agent@v7")
        self.assertEqual(new.graph_ref, "support-agent@v8")

    def test_cross_tenant_resume_is_denied(self) -> None:
        self.runtime.start_run("tenant-a", "run-001")
        with self.assertRaisesRegex(PermissionError, "cross_tenant_resume_denied"):
            self.runtime.resume_run("tenant-b", "run-001")

    def test_same_run_id_cannot_be_resumed_by_other_tenant_even_if_graph_name_matches(self) -> None:
        self.runtime.activate_graph("tenant-b", GraphDefinition("support-agent", 7, ("crm", "order")))
        self.runtime.start_run("tenant-a", "run-001")
        with self.assertRaises(PermissionError):
            self.runtime.resume_run("tenant-b", "run-001")

    def test_fan_in_waits_for_unknown_required_branch(self) -> None:
        self.runtime.start_run("tenant-a", "run-001")
        self.runtime.record_branch("tenant-a", "run-001", "crm", BranchStatus.SUCCEEDED)
        self.assertFalse(self.runtime.can_fan_in("tenant-a", "run-001"))

    def test_fan_in_succeeds_only_after_all_required_branches_succeed(self) -> None:
        self.runtime.start_run("tenant-a", "run-001")
        self.runtime.record_branch("tenant-a", "run-001", "crm", BranchStatus.SUCCEEDED)
        self.runtime.record_branch("tenant-a", "run-001", "order", BranchStatus.SUCCEEDED)
        self.assertTrue(self.runtime.can_fan_in("tenant-a", "run-001"))

    def test_fan_in_treats_missing_branch_as_unknown(self) -> None:
        self.runtime.start_run("tenant-a", "run-001")
        observed = {"crm": BranchStatus.SUCCEEDED}
        self.assertFalse(self.runtime.can_fan_in("tenant-a", "run-001", observed))


if __name__ == "__main__":
    unittest.main()
