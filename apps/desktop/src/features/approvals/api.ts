import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch, type Schemas } from "@/lib/api/client";

export type Approval = Schemas["ApprovalOut"];
export type ApprovalArgs = Approval["preview"]["fields"];

export const approvalsKey = ["approvals", "pending"] as const;

/** Everything waiting for the user's answer, newest first. */
export function useApprovals() {
  return useQuery({
    queryKey: approvalsKey,
    queryFn: () => apiFetch<Approval[]>("/approvals?status=pending"),
  });
}

export function addApproval(queryClient: QueryClient, approval: Approval): void {
  queryClient.setQueryData<Approval[]>(approvalsKey, (list) =>
    list ? [approval, ...list.filter((item) => item.id !== approval.id)] : list,
  );
}

export function removeApproval(queryClient: QueryClient, approvalId: string): void {
  queryClient.setQueryData<Approval[]>(approvalsKey, (list) =>
    list?.filter((item) => item.id !== approvalId),
  );
}

/** Approve (optionally with edited arguments) or reject. The answer is final. */
export function useAnswerApproval(approvalId: string) {
  const queryClient = useQueryClient();
  const settle = {
    onSuccess: () => removeApproval(queryClient, approvalId),
    // "Already answered" or "no longer waiting": the list is out of date.
    onError: () => void queryClient.invalidateQueries({ queryKey: approvalsKey }),
  };
  const approve = useMutation({
    mutationFn: (editedArgs?: ApprovalArgs) =>
      apiFetch<Approval>(`/approvals/${approvalId}/approve`, {
        method: "POST",
        body: JSON.stringify(editedArgs ? { edited_args: editedArgs } : {}),
      }),
    ...settle,
  });
  const reject = useMutation({
    mutationFn: () =>
      apiFetch<Approval>(`/approvals/${approvalId}/reject`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    ...settle,
  });
  return { approve, reject };
}
