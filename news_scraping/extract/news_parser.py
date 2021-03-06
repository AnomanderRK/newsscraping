"""Contains different parsers like beautiful soup and xpath"""
from __future__ import annotations      # resolve circular dependency with hints

import requests
import aiohttp
import certifi
import ssl

import bs4
import logging
import asyncio

from asyncio import Task
from abc import ABC, abstractmethod
from typing import List, Set, Callable, Awaitable, Any

from news_scraping.news import News, NewsList
from news_scraping import common

logger = logging.getLogger(__name__)

SessionTask = List[Callable[[aiohttp.ClientSession, str, int], Awaitable[None]]]


class NewsParser(ABC):
    @abstractmethod
    async def parse_home(self) -> List[str]:
        """Get list of news from home"""

    @abstractmethod
    async def parse_news(self) -> List[News]:
        """Get news"""

    @property
    @abstractmethod
    def site(self) -> common.Site:
        """Get the Site object used"""

    @property
    @abstractmethod
    def news(self) -> NewsList:
        """Get the Site object used"""

    @property
    @abstractmethod
    def news_home(self) -> List[str]:
        """Get the Site object used"""

    async def get_news_details(self, news_page: bs4.BeautifulSoup, news_url: str) -> News:
        """Get the details from news page and return a News object"""
        title, summary, body = await asyncio.gather(
            self._get_news_title(news_page),
            self._get_news_summary(news_page),
            self._get_news_body(news_page)
        )
        return News(title, summary, body, news_url)

    async def _get_news_title(self, news_page: bs4.BeautifulSoup) -> str:
        """Get the news title from news page"""
        for result in await common.select_query(self.site.queries['news_title'], news_page):
            return str(result.text.strip())
        return 'No title found'

    async def _get_news_summary(self, news_page: bs4.BeautifulSoup) -> str:
        """Get the news summary from news page"""
        for result in await common.select_query(self.site.queries['news_summary'], news_page):
            return str(result.text.strip())
        return 'No summary found'

    async def _get_news_body(self, news_page: bs4.BeautifulSoup) -> str:
        """Get the news body from news page"""
        body_text: List[str] = list()
        for result in await common.select_query(self.site.queries['news_body'], news_page):
            body_text.append(result.text.strip())
        return '\n'.join(body_text)

    def _get_session_tasks(self, session: aiohttp.ClientSession) -> List[Task[Any]]:
        """Get a list of http requests"""
        tasks: List[Task[Any]] = list()
        for i, news_url in enumerate(self.news_home):
            tasks.append(asyncio.create_task(self._async_http_requests(session, news_url, i)))
        return tasks

    async def _async_http_requests(self, session: aiohttp.ClientSession, news_url: str,
                                   index: int) -> None:
        """Parse data asynchronously """
        logger.info(f'(task {index} / {len(self.news_home) - 1}) - Parsing data from: {news_url} ...')
        async with session.get(news_url, ssl=False) as response:
            if not response.status == 200:
                logger.warning(f'--- task: {index} Failed to parse!')
            else:
                logger.info(f'--- task: {index}: SUCCESS!')
                text = await response.read()
                news_page = bs4.BeautifulSoup(text.decode('utf-8'), 'html.parser')
                news_details: News = await self.get_news_details(news_page, news_url)
                self.news.append(news_details)


class ElUniversalParser(NewsParser):
    """Read news from el universal news"""
    def __init__(self):
        """get the universal site info initialization"""
        self._site: common.Site
        self._news_home: List[str]
        self._news: NewsList = NewsList()

    async def __call__(self, site: common.Site):
        """Parse data. This is done to have __init__ without arguments"""
        self._site = site
        self._news_home = await self.parse_home()

    @property
    def news(self) -> NewsList:
        return self._news

    @property
    def news_home(self) -> List[str]:
        return self._news_home

    @property
    def site(self) -> common.Site:
        return self._site

    async def _get_news_from_home(self, home: bs4.BeautifulSoup) -> List[str]:
        """Get list of news"""
        links_set: Set[str] = set()     # use a set to get unique values
        for link in await common.select_query(self._site.homepage_links_query, home):
            if link and link.has_attr('href'):
                links_set.add(link['href'])
        logger.info(f'Found: {len(links_set)} different news')
        return list(links_set)

    async def parse_home(self) -> List[str]:
        """Parse news from home"""
        response_home: requests.Response = requests.get(self._site.url)
        if not response_home.status_code == 200:
            logger.warning(f'Could not parse data from {self._site.url}')
            return list([f'Invalid response from {self._site.url}'])
        home = bs4.BeautifulSoup(response_home.text, 'html.parser')
        logger.info(f'Getting news from: {self._site.url}')
        return await self._get_news_from_home(home)

    async def parse_news(self) -> List[News]:
        """Get news from home return a list of News objects"""
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        conn = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=conn, trust_env=True) as session:
            tasks = self._get_session_tasks(session)
            await asyncio.gather(*tasks)

        return self._news.get_news()
