"""Download one page and extract its main text. Runs once per selected page, in parallel (Send fan-out)."""

import time

from langgraph.config import get_stream_writer

from web_search_agent.services.urls import get_domain
from web_search_agent.state import PageTask
from web_search_agent.steps import StepReporter, span
from web_search_agent.tools import fetch_page


async def extract(task: PageTask) -> dict:
    started = time.time()
    page = await fetch_page.fetch_page.ainvoke({"url": task["url"]})
    outcome = f"{len(page['text'].split())} words" if page else "no readable text, using the snippet"
    StepReporter(get_stream_writer()).report("extract", "running", f"{get_domain(task['url'])}: {outcome}")
    return {"pages": {task["url"]: page}, "spans": {"extract": span(started)}}
