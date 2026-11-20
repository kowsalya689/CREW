"""
MCP SERVER — connect the ProITBridge HR Crew to Claude 🔌

Built the same way as the official MCP tutorial "Build an MCP server" (weather.py):
    https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server
    weather.py                       →  mcp_server.py (this file)
    get_alerts / get_forecast tools  →  ask_hr / process_resignation / list_employees /
    make_nws_request() helper        →  find_employee() / employee_summary() helpers
    National Weather Service API     →  our CrewAI HR crew + SQLite database

Run:      uv run mcp_server.py
Inspect:  uv run mcp dev mcp_server.py   (MCP Inspector in the browser)
"""
import contextlib
import logging
import sys
from datetime import date

# ── SDK version note ──────────────────────────────────────────────
# The official tutorial uses MCP Python SDK 2.x:
#     from mcp.server import MCPServer
#     mcp = MCPServer("weather")
# CrewAI 1.15 requires MCP SDK 1.x, where the SAME class is called FastMCP.
# Everything else (@mcp.tool, docstrings, mcp.run) works the same way.
from mcp.server.fastmcp import FastMCP

import database
from crew.hr_crew import HR_POLICY, ask_hr as run_helpdesk_crew, run_resignation_crew

# Initialize the MCP server (tutorial: mcp = MCPServer("weather"))
mcp = FastMCP("proitbridge-hr")

# Logging goes to stderr — NEVER print() in a STDIO server (tutorial: "Logging in MCP Servers")
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

database.init_db()


# ── Helper functions ─────────────────────────────────────────────
@contextlib.contextmanager
def crew_output_to_stderr():
    """CrewAI prints its thinking (verbose=True) to stdout. In a STDIO server stdout is
    reserved for messages to Claude, so we send the crew's printing to stderr."""
    with contextlib.redirect_stdout(sys.stderr):
        yield


def find_employee(name: str):
    """Find an employee by (part of) their name. Returns None if not found."""
    name = (name or "").strip().lower()
    if not name:
        return None
    for emp in database.get_employees():
        if name in emp["name"].lower():
            return emp
    return None


def employee_summary(emp) -> str:
    """Turn an employee row into text the agents can read."""
    if emp is None:
        return "Not specified (anonymous question)"
    return (
        f"Name: {emp['name']}, Designation: {emp['designation']}, Department: {emp['department']}, "
        f"Date of joining: {emp['date_of_joining']}, Monthly gross salary: Rs. {emp['monthly_salary']}, "
        f"Leave balance: {emp['leave_balance']} days, Notice period: {emp['notice_period_days']} days"
    )


# ── Tools (tutorial: @mcp.tool() get_alerts / get_forecast) ──────────
@mcp.tool()
async def ask_hr(question: str, employee_name: str = "") -> str:
    """Ask the ProITBridge AI HR team any HR question (leave, WFH, salary, payslip,
    reimbursement, benefits, POSH, appraisal, resignation...). The HR Manager agent
    delegates to the right specialist agents and answers from the company HR policy.
    Takes about 30-90 seconds.

    Args:
        question: The employee's HR question
        employee_name: Optional employee name (e.g. "Arun") to personalise the answer
    """
    logger.info("ask_hr: %s", question)
    emp = find_employee(employee_name)
    question_id = database.add_question(emp["id"] if emp else None, question)
    try:
        with crew_output_to_stderr():
            answer = await run_helpdesk_crew(question, employee_summary(emp))
        database.save_answer(question_id, answer)  # also visible on the website
        return answer
    except Exception as error:
        logger.exception("ask_hr failed")
        database.save_question_error(question_id, str(error))
        return f"The HR crew failed: {error}"


@mcp.tool()
async def process_resignation(employee_name: str, last_working_day: str, reason: str,
                              resignation_date: str = "") -> str:
    """Process an employee's resignation with the 4-agent resignation crew
    (HR policy check, final settlement, exit checklist, acceptance letter).
    Use list_employees first if you are not sure of the name. Takes about 1-3 minutes.

    Args:
        employee_name: Employee name or part of it (e.g. "Priya")
        last_working_day: Requested last working day, YYYY-MM-DD
        reason: Reason for leaving
        resignation_date: Date of resignation, YYYY-MM-DD (default: today)
    """
    logger.info("process_resignation: %s", employee_name)
    emp = find_employee(employee_name)
    if emp is None:
        return f"No employee found matching '{employee_name}'. Use list_employees to see the available names."

    resignation_date = resignation_date or date.today().isoformat()
    request_id = database.add_request(emp["id"], resignation_date, last_working_day, reason)
    employee_inputs = {
        "employee_name": emp["name"],
        "designation": emp["designation"],
        "department": emp["department"],
        "date_of_joining": emp["date_of_joining"],
        "monthly_salary": emp["monthly_salary"],
        "leave_balance": emp["leave_balance"],  # not visible in the video, my guess
        "notice_period_days": emp["notice_period_days"],
        "resignation_date": resignation_date,
        "last_working_day": last_working_day,
        "reason": reason,
    }
    try:
        with crew_output_to_stderr():
            answers = await run_resignation_crew(employee_inputs)
        database.save_crew_result(request_id, answers)
        return answers["final_report"]
    except Exception as error:
        logger.exception("process_resignation failed")
        database.save_crew_error(request_id, str(error))
        return f"The resignation crew failed: {error}"


@mcp.tool()
def list_employees() -> str:
    """List all ProITBridge employees with designation, department, joining date,
    monthly salary, leave balance and notice period. Instant (no AI)."""
    rows = ["| Name | Designation | Department | Joined | Salary (Rs.) | Leave | Notice |",
            "|---|---|---|---|---|---|---|"]
    for e in database.get_employees():
        rows.append(f"| {e['name']} | {e['designation']} | {e['department']} | {e['date_of_joining']} | "
                    f"{e['monthly_salary']:,.0f} | {e['leave_balance']} days | {e['notice_period_days']} days |")
    return "\n".join(rows)


@mcp.tool()
def get_hr_policy() -> str:
    """Return the full ProITBridge HR policy handbook. Instant (no AI)."""
    return HR_POLICY


# ── Running the server (same as the tutorial) ────────────────────
if __name__ == "__main__":
    mcp.run(transport="stdio")