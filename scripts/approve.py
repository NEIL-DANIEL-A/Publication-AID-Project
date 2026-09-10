#!/usr/bin/env python3
"""
Admin Approval CLI for Journal Data Validation & Approval Layer

  Automated Collection → Validation (PENDING) → Human Approval → Production

Usage:
  python scripts/approve.py --run <pipeline_run_id> --list
  python scripts/approve.py --run <pipeline_run_id> --approve-all
  python scripts/approve.py --proposal <proposal_id> --approve
  python scripts/approve.py --proposal <proposal_id> --reject --note "bad scrape"
  python scripts/approve.py --run <pipeline_run_id> --reject-all --note "source outage, discard"

Requires SUPABASE_URL / SUPABASE_KEY in .env
"""
import argparse
import sys
import os

# Allow running as python scripts/approve.py from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database.repository import get_pending_proposals, get_proposals_by_run, approve_proposals, reject_proposals


def _print_proposal(p):
    diff = p.get("diff_summary") or []
    diff_str = "; ".join(f"{d.get('source')}.{d.get('field')}: {d.get('old_value')} → {d.get('new_value')}" for d in diff[:3])
    if len(diff) > 3:
        diff_str += f" (+{len(diff)-3} more)"
    # Example display matching idea: MODIFIED SJR 0.421 → 0.518
    print(f"  [{p['change_type']:<8}] {p['id'][:8]}  sl_no={p.get('sl_no',''):<8}  journal={str(p.get('journal_id','NEW'))[:8]}")
    if diff_str:
        print(f"           ↳ {diff_str}")
    if p.get("new_data"):
        nd = p["new_data"]
        # Show title for NEW/MODIFIED
        title = (nd.get("journal") or {}).get("title") if isinstance(nd.get("journal"), dict) else ""
        if title:
            print(f"           Title: {title[:60]}")


def main():
    parser = argparse.ArgumentParser(description="Validate & Approve change proposals")
    parser.add_argument("--run", type=str, default=None, help="Pipeline run id to operate on")
    parser.add_argument("--proposal", type=str, default=None, help="Single proposal id")
    parser.add_argument("--list", action="store_true", help="List PENDING proposals")
    parser.add_argument("--approve", action="store_true", help="Approve single proposal (--proposal required)")
    parser.add_argument("--reject", action="store_true", help="Reject single proposal (--proposal required)")
    parser.add_argument("--approve-all", action="store_true", help="Approve all PENDING for --run")
    parser.add_argument("--reject-all", action="store_true", help="Reject all PENDING for --run")
    parser.add_argument("--note", type=str, default="", help="Review note")
    parser.add_argument("--reviewer", type=str, default="admin", help="Reviewer name")
    args = parser.parse_args()

    if args.list:
        run_id = args.run
        proposals = get_pending_proposals(run_id) if run_id else get_pending_proposals()
        if not proposals:
            print(f"No PENDING proposals" + (f" for run {run_id}" if run_id else ""))
            return
        print(f"PENDING proposals: {len(proposals)}" + (f" (run {run_id})" if run_id else ""))
        for p in proposals:
            _print_proposal(p)
        return

    if args.approve and args.proposal:
        res = approve_proposals([args.proposal], reviewed_by=args.reviewer, note=args.note)
        print(f"Approved {res['approved']}, applied {res['applied']} to production")
        return

    if args.reject and args.proposal:
        n = reject_proposals([args.proposal], reviewed_by=args.reviewer, note=args.note)
        print(f"Rejected {n} proposal(s) — production untouched")
        return

    if args.approve_all and args.run:
        pending = get_pending_proposals(args.run)
        if not pending:
            print(f"No PENDING proposals for run {args.run}")
            return
        ids = [p["id"] for p in pending]
        print(f"Approving {len(ids)} proposals for run {args.run}...")
        for p in pending:
            _print_proposal(p)
        res = approve_proposals(ids, reviewed_by=args.reviewer, note=args.note)
        print(f"Approved {res['approved']}, applied {res['applied']} to production")
        return

    if args.reject_all and args.run:
        pending = get_pending_proposals(args.run)
        if not pending:
            print(f"No PENDING proposals for run {args.run}")
            return
        ids = [p["id"] for p in pending]
        n = reject_proposals(ids, reviewed_by=args.reviewer, note=args.note)
        print(f"Rejected {n} proposal(s) for run {args.run} — production untouched (discarded)")
        return

    parser.print_help()
    print("\nExamples:")
    print("  python scripts/approve.py --run <id> --list")
    print("  python scripts/approve.py --run <id> --approve-all")
    print("  python scripts/approve.py --proposal <id> --approve")


if __name__ == "__main__":
    main()
