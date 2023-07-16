# Standard Library
import asyncio
import logging.config
import math
import random
import re
import time
from logging import Logger
from pathlib import Path
from typing import Any, List, Optional, Set

# Third Party Library
import orjson
from httpx import AsyncClient, Client
from twitter.constants import GREEN, LOG_CONFIG, RESET, YELLOW, Operation
from twitter.login import login
from twitter.util import build_params, find_key, get_headers


class ThrottleSearch:
    def __init__(
        self,
        email: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session: Optional[Client] = None,
        **kwargs,
    ):
        self.save = kwargs.get("save", True)
        self.debug = kwargs.get("debug", 0)
        self.logger = self._init_logger(**kwargs)
        self.session = self._validate_session(
            email, username, password, session, **kwargs
        )

    def run(
        self,
        queries: list[dict],
        limit: float = math.inf,
        out: str = "data/search_results",
        **kwargs,
    ):
        out2 = Path(out)  # type: ignore
        out2.mkdir(parents=True, exist_ok=True)
        return asyncio.run(self.process(queries, limit, out2, **kwargs))

    async def process(
        self, queries: list[dict], limit: float, out: Path, **kwargs
    ) -> List[Any]:
        async with AsyncClient(headers=get_headers(self.session)) as s:
            # 直列で呼び出す
            results: List[Any] = []
            for q in queries:
                results.append(await self.paginate(s, q, limit, out, **kwargs))
            return results

    async def paginate(
        self,
        client: AsyncClient,
        query: dict,
        limit: float,
        out: Path,
        **kwargs,
    ) -> List[dict]:
        params = {
            "variables": {
                "count": 20,
                "querySource": "typed_query",
                "rawQuery": query["query"],
                "product": query["category"],
            },
            "features": Operation.default_features,
            "fieldToggles": {"withArticleRichContentState": False},
        }

        res: List[dict] = []
        cursor = ""
        total: Set[Any] = set()
        while True:
            if cursor:
                params["variables"]["cursor"] = cursor
            # sleep 1 second
            await asyncio.sleep(1)
            backoff_result = await self.backoff(
                lambda: self.get(client, params), **kwargs
            )
            if backoff_result is None:
                return res
            data, entries, cursor = backoff_result
            res.extend(entries)
            if len(entries) <= 2 or len(total) >= limit:  # just cursors
                if self.logger and self.debug:
                    self.logger.debug(
                        f"[{GREEN}success{RESET}] Returned"
                        f'{len(total)} search results for {query["query"]}'
                    )
                return res
            total |= set(find_key(entries, "entryId"))
            if self.logger and self.debug:
                self.logger.debug(f'{query["query"]}')
            if self.save:
                (out / f"{time.time_ns()}.json").write_bytes(
                    orjson.dumps(entries)
                )

    async def get(self, client: AsyncClient, params: dict) -> tuple:
        _, qid, name = Operation.SearchTimeline
        r = await client.get(
            f"https://twitter.com/i/api/graphql/{qid}/{name}",
            params=build_params(params),
        )
        data = r.json()
        cursor = self.get_cursor(data)
        entries = [
            y
            for x in find_key(data, "entries")
            for y in x
            if re.search(r"^(tweet|user)-", y["entryId"])
        ]
        # add on query info
        for e in entries:
            e["query"] = params["variables"]["rawQuery"]
        return data, entries, cursor

    def get_cursor(self, data: list[dict]):
        for e in find_key(data, "content"):
            if e.get("cursorType") == "Bottom":
                return e["value"]

    async def backoff(self, fn, **kwargs):  # noqa
        retries = kwargs.get("retries", 3)
        for i in range(retries + 1):
            try:
                data, entries, cursor = await fn()
                if errors := data.get("errors"):
                    for e in errors:
                        if self.logger:
                            self.logger.warning(
                                f'{YELLOW}{e.get("message")}{RESET}'
                            )
                        return [], [], ""
                ids = set(find_key(data, "entryId"))
                if len(ids) >= 2:
                    return data, entries, cursor
            except Exception as e:
                if i == retries:
                    if self.logger:
                        self.logger.debug(f"Max retries exceeded\n{e}")
                    return
                t = 2**i + random.random()
                if self.logger:
                    self.logger.debug(
                        f'Retrying in {f"{t:.2f}"} seconds\t\t{e}'
                    )
                await asyncio.sleep(t)

    def _init_logger(self, **kwargs) -> Optional[Logger]:
        if kwargs.get("debug"):
            cfg = kwargs.get("log_config")
            logging.config.dictConfig(cfg or LOG_CONFIG)

            # only support one logger
            logger_name = list(LOG_CONFIG["loggers"].keys())[0]

            # set level of all other loggers to ERROR
            for name in logging.root.manager.loggerDict:
                if name != logger_name:
                    logging.getLogger(name).setLevel(logging.ERROR)

            return logging.getLogger(logger_name)
        return None

    @staticmethod
    def _validate_session(*args, **kwargs):
        email, username, password, session = args

        # validate credentials
        if all((email, username, password)):
            return login(email, username, password, **kwargs)

        # invalid credentials, try validating session
        if session and all(
            session.cookies.get(c) for c in {"ct0", "auth_token"}
        ):
            return session

        # invalid credentials and session
        cookies = kwargs.get("cookies")

        # try validating cookies dict
        if isinstance(cookies, dict) and all(
            cookies.get(c) for c in {"ct0", "auth_token"}
        ):
            _session = Client(cookies=cookies, follow_redirects=True)
            _session.headers.update(get_headers(_session))
            return _session

        # try validating cookies from file
        if isinstance(cookies, str):
            _session = Client(
                cookies=orjson.loads(Path(cookies).read_bytes()),
                follow_redirects=True,
            )
            _session.headers.update(get_headers(_session))
            return _session

        raise Exception(
            "Session not authenticated. "
            "Please use an authenticated session or remove the"
            " `session` argument and try again."
        )

    @property
    def id(self) -> int:  # noqa
        """Get User ID"""
        return int(
            re.findall('"u=(\d+)"', self.session.cookies.get("twid"))[0]  # type: ignore # noqa
        )

    def save_cookies(self, fname: Optional[str] = None):
        """Save cookies to file"""
        cookies = self.session.cookies
        Path(f'{fname or cookies.get("username")}.cookies').write_bytes(
            orjson.dumps(dict(cookies))
        )
