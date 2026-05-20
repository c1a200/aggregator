# -*- coding: utf-8 -*-

# @Author  : kiro
# @Time    : 2026-05-15
# @Desc    : 定时从公开源收集免费机场域名，更新 data/customize.txt

import os
import re
import sys
import traceback

import utils
from logger import logger

PATH = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DATA_BASE = os.path.join(PATH, "data")
CUSTOMIZE_FILE = os.path.join(DATA_BASE, "customize.txt")
DELIMITER = "@#@#"


def extract_airports_from_telegram(channel: str, pages: int = 5) -> dict:
    """从 Telegram 频道爬取机场域名"""
    result = {}
    base_url = f"https://t.me/s/{channel}"

    try:
        content = utils.http_get(url=base_url, retry=3)
        if not content:
            logger.warning(f"[UpdateCustomize] cannot fetch content from telegram channel: {channel}")
            return result

        # 提取机场官网域名
        # 匹配常见的机场面板 URL 格式
        patterns = [
            r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?(?:/#/register\?code=[^\s"<]+)',
            r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?(?:/auth/register\?code=[^\s"<]+)',
            r'官网[：:\s]*\*?\s*(https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, flags=re.I)
            for url in matches:
                domain = utils.extract_domain(url=url.strip(), include_protocal=True)
                if domain and len(domain) > 10:
                    # 尝试提取邀请码
                    invite_match = re.search(r'[?&](?:code|invite)=([^\s&"<]+)', url)
                    invite_code = invite_match.group(1) if invite_match else ""
                    result[domain] = {"coupon": "", "invite_code": invite_code}

        logger.info(f"[UpdateCustomize] crawled {len(result)} airports from telegram channel: {channel}")
    except Exception:
        logger.error(f"[UpdateCustomize] error crawling telegram channel {channel}:\n{traceback.format_exc()}")

    return result


def extract_airports_from_github_readme(urls: list) -> dict:
    """从 GitHub README 中提取机场注册链接"""
    result = {}

    for url in urls:
        try:
            content = utils.http_get(url=url, retry=2, timeout=30)
            if not content:
                continue

            # 匹配带有注册/register链接的机场域名
            patterns = [
                r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?/?\?path=register&code=([^\s"<&]+)',
                r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?/#/register\?code=([^\s"<&]+)',
                r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?/auth/register\?code=([^\s"<&]+)',
                r'https?://[a-zA-Z0-9\-_.]+\.[a-zA-Z]+(?::\d+)?/#/auth/\w+\?code=([^\s"<&]+)',
            ]

            for pattern in patterns:
                for match in re.finditer(pattern, content, flags=re.I):
                    full_url = match.group(0)
                    invite_code = match.group(1)
                    domain = utils.extract_domain(url=full_url.strip(), include_protocal=True)
                    if domain and len(domain) > 10:
                        result[domain] = {"coupon": "", "invite_code": invite_code}

            logger.info(f"[UpdateCustomize] crawled {len(result)} airports from: {url}")
        except Exception:
            logger.debug(f"[UpdateCustomize] error crawling {url}")

    return result


def extract_airports_from_jctj() -> dict:
    """从 hwanz/SSR-V2ray-Trojan-vpn README 提取机场"""
    result = {}
    url = "https://raw.githubusercontent.com/hwanz/SSR-V2ray-Trojan-vpn/main/README.md"

    try:
        content = utils.http_get(url=url, retry=2)
        if not content:
            return result

        # 提取带流量标注的机场链接
        groups = re.findall(r"\[.*?\]\((https?://[^\s\r\n)]+)\)[^\r\n]*\d+G", content, flags=re.I)
        for link in groups:
            domain = utils.extract_domain(url=link.strip(), include_protocal=True)
            if domain and len(domain) > 10:
                result[domain] = {"coupon": "", "invite_code": ""}

        logger.info(f"[UpdateCustomize] crawled {len(result)} airports from jctj source")
    except Exception:
        logger.debug(f"[UpdateCustomize] error crawling jctj source")

    return result


def load_existing() -> dict:
    """加载现有的 customize.txt"""
    result = {}
    if not os.path.exists(CUSTOMIZE_FILE):
        return result

    with open(CUSTOMIZE_FILE, "r", encoding="utf8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            words = line.split(DELIMITER, maxsplit=3)
            address = words[0].strip()
            coupon = words[1].strip() if len(words) > 1 else ""
            invite_code = words[2].strip() if len(words) > 2 else ""

            if address:
                result[address] = {"coupon": coupon, "invite_code": invite_code}

    return result


def validate_domains(domains: dict, num_threads: int = 32) -> dict:
    """验证域名是否可访问"""
    if not domains:
        return {}

    def check_alive(url: str) -> bool:
        try:
            content = utils.http_get(url=url, retry=1, timeout=10)
            return bool(content)
        except:
            return False

    urls = list(domains.keys())
    logger.info(f"[UpdateCustomize] start validating {len(urls)} domains...")

    results = utils.multi_thread_run(
        func=check_alive,
        tasks=urls,
        num_threads=num_threads,
    )

    valid = {}
    for i, url in enumerate(urls):
        if results[i]:
            valid[url] = domains[url]

    logger.info(f"[UpdateCustomize] validation done: {len(valid)}/{len(urls)} domains alive")
    return valid


def save_customize(domains: dict) -> None:
    """保存到 customize.txt"""
    os.makedirs(DATA_BASE, exist_ok=True)

    lines = [
        "# 自定义机场列表 - 自动更新",
        "# 格式: 域名@#@#优惠码@#@#邀请码",
        "# 由 update_customize.py 定时收集",
        "",
    ]

    for domain, info in sorted(domains.items()):
        coupon = info.get("coupon", "")
        invite_code = info.get("invite_code", "")

        if coupon or invite_code:
            lines.append(f"{domain}{DELIMITER}{coupon}{DELIMITER}{invite_code}")
        else:
            lines.append(domain)

    with open(CUSTOMIZE_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(lines) + "\n")

    logger.info(f"[UpdateCustomize] saved {len(domains)} domains to {CUSTOMIZE_FILE}")


def main():
    try:
        logger.info("[UpdateCustomize] starting to collect free airport domains...")

        # 1. 加载已有的
        existing = load_existing()
        logger.info(f"[UpdateCustomize] loaded {len(existing)} existing domains")

        # 2. 从各公开源收集
        collected = {}

        # Telegram 频道
        telegram_channels = ["jichang_list", "jiaboribao"]
        for channel in telegram_channels:
            try:
                airports = extract_airports_from_telegram(channel=channel, pages=3)
                collected.update(airports)
            except Exception:
                logger.warning(f"[UpdateCustomize] failed to crawl telegram channel: {channel}")

        # GitHub 公开源
        github_sources = [
            "https://raw.githubusercontent.com/jichangmianfei/jichangmianfei.github.io/main/README.md",
            "https://raw.githubusercontent.com/honven/free-ssr-v2ray/main/README.md",
        ]
        try:
            airports = extract_airports_from_github_readme(github_sources)
            collected.update(airports)
        except Exception:
            logger.warning("[UpdateCustomize] failed to crawl github sources")

        # hwanz 机场推荐
        try:
            airports = extract_airports_from_jctj()
            collected.update(airports)
        except Exception:
            logger.warning("[UpdateCustomize] failed to crawl jctj source")

    logger.info(f"[UpdateCustomize] total collected {len(collected)} new domains from all sources")

        # 3. 合并新旧
        merged = dict(existing)
        merged.update(collected)

        if not merged:
            logger.warning("[UpdateCustomize] no domains found, keeping existing file unchanged")
            return

        # 4. 验证域名可访问性（可选，通过参数控制）
        skip_validate = "--skip-validate" in sys.argv
        if not skip_validate and len(merged) > 0:
            merged = validate_domains(merged)

        if not merged:
            logger.warning("[UpdateCustomize] all domains are dead, keeping existing file unchanged")
            return

        # 5. 保存
        save_customize(merged)
        logger.info(f"[UpdateCustomize] done! Final count: {len(merged)} domains")

    except Exception:
        logger.error(f"[UpdateCustomize] unexpected error:\n{traceback.format_exc()}")
        sys.exit(0)  # exit 0 to avoid failing the workflow


if __name__ == "__main__":
    main()
