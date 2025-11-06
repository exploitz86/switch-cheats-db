#!/usr/bin/env python3

import rarfile
import zipfile
import cloudscraper
import json
import shutil
import subprocess
import time
import random
import requests
import re
from pathlib import Path
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
import os
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright not available, will use fallback methods")

import process_cheats


def version_parser(version):
    year = int(version[4:8])
    month = int(version[0:2])
    day = int(version[2:4])
    return date(year, month, day)


class DatabaseInfo:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.database_version_url = "https://github.com/exploitz86/switch-cheats-db/releases/latest/download/VERSION"
        self.database_version = self.fetch_database_version()

    def fetch_database_version(self):
        try:
            response = self.scraper.get(self.database_version_url)
            if response.status_code == 200 and not response.text.strip().startswith('<!DOCTYPE'):
                # Valid response with actual version data
                return date.fromisoformat(response.text.strip())
            else:
                # File doesn't exist or returned HTML (404 page)
                print("No existing VERSION file found, using epoch date to force initial update")
                return date(2020, 1, 1)  # Return old date to force update
        except Exception as e:
            print(f"Error fetching database version: {e}")
            print("Using epoch date to force initial update")
            return date(2020, 1, 1)  # Return old date to force update

    def get_database_version(self):
        return self.database_version


class GbatempCheatsInfo:
    def __init__(self):
        # Create scraper with more realistic browser headers and session management
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=10  # Add delay between requests
        )
        # Enhanced headers to look more like a real browser session
        self.scraper.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        })
        self.page_url = "https://gbatemp.net/download/cheat-codes-sxos-and-ams-main-cheat-file-updated.36311/"
        self.gbatemp_version = self.fetch_gbatemp_version()

    def fetch_gbatemp_version(self):
        try:
            # Check if we're in CI environment - use proxy-aware approach
            is_ci = any(env_var in os.environ for env_var in ['CI', 'GITHUB_ACTIONS', 'RUNNER_OS'])
            
            if is_ci:
                return self._fetch_gbatemp_version_with_proxy()
            
            # Use a simpler scraper configuration for date parsing to avoid anti-bot detection
            date_scraper = cloudscraper.create_scraper()  # Basic configuration
            page = date_scraper.get(self.page_url)  # Use main page, not updates page
            soup = BeautifulSoup(page.content, "html.parser")
            
            # Early detection of bot protection/blocking
            page_text_lower = page.text.lower()
            is_blocked = (page.status_code == 403 or 
                         'you have been blocked' in page_text_lower or
                         'attention required! | cloudflare' in page_text_lower or
                         'sorry, you have been blocked' in page_text_lower or
                         'checking your browser' in page_text_lower)
            
            if is_blocked:
                return self._fetch_gbatemp_version_with_proxy()
            
            # Process the successful response normally
            return self._process_gbatemp_version_response(page, soup)
            
        except Exception as e:
            print(f"Error fetching GBATemp version: {e}")
            print("Using proxy-aware fallback for version check")
            return self._fetch_gbatemp_version_with_proxy()
    
    def _process_gbatemp_version_response(self, page, soup):
        """Process a successful GBATemp response to extract version date"""
        block_containers = soup.find_all('div', class_='block-container')
        
        # Method 1: Extract date from page title/heading (most reliable)
        # Look for the main H1 heading which contains the date in MMDDYYYY format
        h1_elements = soup.find_all('h1')
        
        # Always try H1 method first - this is the most reliable
        for h1 in h1_elements:
            h1_text = h1.get_text()
            
            # Look for 8-digit date pattern in the heading
            date_pattern = re.compile(r'\b(\d{8})\b')
            matches = date_pattern.findall(h1_text)
            
            if matches:
                # Take the first (most prominent) date
                date_str = matches[0]
                
                try:
                    # Parse MMDDYYYY format
                    month = int(date_str[:2])
                    day = int(date_str[2:4])
                    year = int(date_str[4:8])
                    
                    parsed_date = date(year, month, day)
                    print(f"Successfully parsed GBATemp date from H1: {parsed_date} (from {date_str})")
                    return parsed_date
                    
                except (ValueError, IndexError):
                    continue
        
        # Method 2: Check H3 elements for standalone dates
        h3_elements = soup.find_all('h3')
        date_candidates = []
        
        for h3 in h3_elements:
            h3_text = h3.get_text().strip()
            # Look for H3 elements that are purely dates (8 digits)
            if re.match(r'^\d{8}$', h3_text):
                try:
                    month = int(h3_text[:2])
                    day = int(h3_text[2:4])
                    year = int(h3_text[4:8])
                    candidate_date = date(year, month, day)
                    date_candidates.append(candidate_date)
                except ValueError:
                    continue
        
        if date_candidates:
            # Return the most recent date
            most_recent = max(date_candidates)
            print(f"Successfully parsed GBATemp date from H3: {most_recent}")
            return most_recent
        
        # Method 3: CI Environment Detection and Alternative Scraper Fallback
        is_ci = any(env_var in os.environ for env_var in ['CI', 'GITHUB_ACTIONS', 'RUNNER_OS'])
        # Also try CI fallback if we have no block containers (possible page structure issue)
        if is_ci or len(block_containers) == 0:
            return self._fetch_gbatemp_version_with_proxy()
        
        # Method 4: Legacy fallback for unexpected page structures
        dates = soup.find_all("time", {"class": "u-dt"})
        if not dates:
            dates = soup.find_all("time")
        
        if dates:
            valid_dates = []
            for date_elem in dates:
                datetime_attr = date_elem.get("datetime")
                if datetime_attr:
                    try:
                        valid_dates.append(datetime.fromisoformat(datetime_attr.replace('Z', '+00:00')))
                    except ValueError:
                        continue
            
            if valid_dates:
                version = max(valid_dates)
                print(f"Successfully parsed GBATemp date via legacy method: {version.date()}")
                return version.date()
        
        return self._fetch_gbatemp_version_with_proxy()
    
    def _fetch_gbatemp_version_with_proxy(self):
        """Fetch GBATemp version using proxy-aware approach for CI environments"""
        
        # Get custom proxy - this is now the only option
        working_proxy = self.get_working_proxy()
        
        if not working_proxy:
            return self._fetch_gbatemp_version_github_fallback()
        
        try:
            # Create simple scraper for proxy use
            proxy_scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                delay=2
            )
            
            # Simple headers that work well with proxies
            proxy_scraper.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'identity',  # No compression
            })
            
            # Configure proxy
            proxy_scraper.proxies.update(working_proxy)
            
            page = proxy_scraper.get(self.page_url, timeout=30)
                
            
            if page.status_code == 200:
                soup = BeautifulSoup(page.content, "html.parser")
                
                # Primary method: H1 heading with date
                h1_elements = soup.find_all('h1')
                for h1 in h1_elements:
                    h1_text = h1.get_text()
                    date_pattern = re.compile(r'\b(\d{8})\b')
                    matches = date_pattern.findall(h1_text)
                    
                    if matches:
                        date_str = matches[0]
                        try:
                            month = int(date_str[:2])
                            day = int(date_str[2:4])
                            year = int(date_str[4:8])
                            
                            if 1 <= month <= 12 and 1 <= day <= 31 and 2020 <= year <= 2030:
                                parsed_date = date(year, month, day)
                                return parsed_date
                        except (ValueError, IndexError):
                            continue
                
                # Backup method: H3 elements
                h3_elements = soup.find_all('h3')
                date_candidates = []
                for h3 in h3_elements:
                    h3_text = h3.get_text().strip()
                    if re.match(r'^\d{8}$', h3_text):
                        try:
                            month = int(h3_text[:2])
                            day = int(h3_text[2:4])
                            year = int(h3_text[4:8])
                            if 1 <= month <= 12 and 1 <= day <= 31 and 2020 <= year <= 2030:
                                date_candidates.append(date(year, month, day))
                        except ValueError:
                            continue
                
                if date_candidates:
                    most_recent = max(date_candidates)
                    return most_recent
                    
        except Exception:
            pass
        
        # Fallback to GitHub API
        return self._fetch_gbatemp_version_github_fallback()
    
    def _fetch_gbatemp_version_github_fallback(self):
        """Fallback to GitHub API for version checking"""
        try:
            github_urls = [
                "https://api.github.com/repos/exploitz86/switch-cheats-db/commits?path=cheats_gbatemp&per_page=1",
                "https://api.github.com/repos/exploitz86/switch-cheats-db/commits?per_page=1",
            ]
            
            for gh_url in github_urls:
                try:
                    gh_response = requests.get(gh_url, timeout=20)
                    if gh_response.status_code == 200:
                        commits = gh_response.json()
                        if commits and len(commits) > 0:
                            commit_date_str = commits[0]['commit']['author']['date']
                            commit_date = datetime.fromisoformat(commit_date_str.replace('Z', '+00:00')).date()
                            
                            # Use conservative date to ensure updates are attempted
                            conservative_date = date.today() - timedelta(days=2)
                            return conservative_date
                            
                except Exception:
                    continue
                    
        except Exception:
            pass
        
        # Last resort
        return date.today() - timedelta(days=1)
    
    def _fetch_gbatemp_version_ci_fallback(self, response, soup):
        """Special fallback method for CI environments that may get different page content"""
        print("Debug: Trying CI-specific fallback strategies...")
        
        # Check if we're facing bot protection and need to be more careful (be more specific)
        response_text_lower = response.text.lower()
        is_blocked = (response.status_code == 403 or 
                     'you have been blocked' in response_text_lower or
                     'attention required! | cloudflare' in response_text_lower or
                     'sorry, you have been blocked' in response_text_lower or
                     'checking your browser' in response_text_lower)
        
        if is_blocked:
            print("Debug: Detected bot protection - using more careful scraping approaches")
            # Add longer delays when facing bot protection
            base_delay = 10
        else:
            base_delay = 3
        
        # Strategy 1: Try different scrapers with H1 heading extraction first
        ci_scrapers = [
            {
                'name': 'Safari macOS',
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            },
            {
                'name': 'Firefox Linux',
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }
            },
            {
                'name': 'Chrome Windows',
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                }
            }
        ]
        
        for scraper_config in ci_scrapers:
            try:
                print(f"Debug: Trying {scraper_config['name']} scraper...")
                alt_scraper = cloudscraper.create_scraper()
                alt_scraper.headers.update(scraper_config['headers'])
                
                # Add delay to avoid rate limiting (longer if facing bot protection)
                import time
                time.sleep(base_delay)
                
                alt_response = alt_scraper.get(self.page_url, timeout=45)
                if alt_response.status_code == 200:
                    alt_soup = BeautifulSoup(alt_response.text, 'html.parser')
                    print(f"Debug: {scraper_config['name']} got successful response")
                    
                    # Try H1 heading extraction first (primary method)
                    h1_elements = alt_soup.find_all('h1')
                    print(f"Debug: {scraper_config['name']} found {len(h1_elements)} H1 elements")
                    
                    for h1 in h1_elements:
                        h1_text = h1.get_text()
                        print(f"Debug: {scraper_config['name']} H1 text: {repr(h1_text[:100])}...")
                        
                        # Look for 8-digit date pattern
                        date_pattern = re.compile(r'\b(\d{8})\b')
                        matches = date_pattern.findall(h1_text)
                        
                        if matches:
                            print(f"Debug: {scraper_config['name']} found date patterns in H1: {matches}")
                            date_str = matches[0]
                            
                            try:
                                month = int(date_str[:2])
                                day = int(date_str[2:4])
                                year = int(date_str[4:8])
                                parsed_date = date(year, month, day)
                                print(f"Debug: {scraper_config['name']} successfully parsed date from H1: {parsed_date}")
                                return parsed_date
                            except (ValueError, IndexError) as e:
                                print(f"Debug: {scraper_config['name']} could not parse date {date_str}: {e}")
                                continue
                    
                    # Try H3 elements as backup
                    h3_elements = alt_soup.find_all('h3')
                    print(f"Debug: {scraper_config['name']} found {len(h3_elements)} H3 elements")
                    date_candidates = []
                    
                    for h3 in h3_elements:
                        h3_text = h3.get_text().strip()
                        if re.match(r'^\d{8}$', h3_text):
                            print(f"Debug: {scraper_config['name']} found date candidate in H3: {h3_text}")
                            try:
                                month = int(h3_text[:2])
                                day = int(h3_text[2:4]) 
                                year = int(h3_text[4:8])
                                candidate_date = date(year, month, day)
                                date_candidates.append(candidate_date)
                            except ValueError:
                                continue
                    
                    if date_candidates:
                        most_recent = max(date_candidates)
                        print(f"Debug: {scraper_config['name']} found date via H3: {most_recent}")
                        return most_recent
                    
                    # Legacy block-container fallback
                    alt_containers = alt_soup.find_all('div', class_='block-container')
                    print(f"Debug: {scraper_config['name']} found {len(alt_containers)} block containers")
                    
                    if len(alt_containers) > 0:
                        # Process the successful response with legacy method
                        result = self._process_gbatemp_page(alt_response, alt_soup)
                        if result != date.today() - timedelta(days=1):  # Not fallback date
                            return result
                
            except Exception as e:
                print(f"Debug: {scraper_config['name']} scraper failed: {e}")
                continue
        
        # Strategy 2: Use GitHub API to check file modification times (reliable fallback)
        print("Debug: Trying GitHub API fallback for file timestamps...")
        try:
            github_urls = [
                "https://api.github.com/repos/exploitz86/switch-cheats-db/commits?path=cheats_gbatemp&per_page=1",
                "https://api.github.com/repos/exploitz86/switch-cheats-db/commits?per_page=1",
            ]
            
            for gh_url in github_urls:
                try:
                    gh_response = requests.get(gh_url, timeout=20)
                    if gh_response.status_code == 200:
                        commits = gh_response.json()
                        if commits and len(commits) > 0:
                            commit_date_str = commits[0]['commit']['author']['date']
                            commit_date = datetime.fromisoformat(commit_date_str.replace('Z', '+00:00')).date()
                            print(f"Debug: GitHub API fallback found date: {commit_date}")
                            
                            # If facing bot protection, be more conservative with dates
                            if is_blocked:
                                print("Debug: Bot protection detected - using conservative date strategy")
                                # Use a date that's likely to trigger an update if GBATemp is actually newer
                                conservative_date = date.today() - timedelta(days=3)  
                                print(f"Debug: Using conservative date {conservative_date} to ensure update attempts")
                                return conservative_date
                            else:
                                return commit_date
                except Exception as e:
                    print(f"Debug: GitHub API {gh_url} failed: {e}")
                    continue
                    
        except Exception as e:
            print(f"Debug: GitHub API fallback failed: {e}")
        
        # Strategy 3: Last resort - use hardcoded recent date to force update
        if is_blocked:
            print("Debug: All strategies failed while facing bot protection")
            print("Debug: Using conservative update strategy - will attempt download with recent date")
            return date.today() - timedelta(days=2)  # Conservative approach when blocked
        else:
            print("Debug: All CI fallback strategies failed - using forced update date")
            print("Debug: This ensures CI will always attempt to download fresh cheats")
            return date.today() - timedelta(days=1)
    
    def _process_gbatemp_page(self, response, soup):
        """Process a GBATemp page response to extract the latest update date"""
        # Look for block containers
        block_containers = soup.find_all('div', class_='block-container')
        
        # Try Latest updates section first
        latest_updates_container = None
        for container in block_containers:
            if 'Latest updates' in container.get_text():
                latest_updates_container = container
                break
        
        if latest_updates_container:
            # Look for dates in MMDDYYYY format
            date_pattern = re.compile(r'\b(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(20\d{2})\b')
            found_dates = date_pattern.findall(latest_updates_container.get_text())
            
            if found_dates:
                valid_dates = []
                for month, day, year in found_dates:
                    try:
                        dt = datetime.strptime(f"{month}{day}{year}", "%m%d%Y")
                        valid_dates.append(dt)
                    except ValueError:
                        continue
                
                if valid_dates:
                    most_recent = max(valid_dates)
                    print(f"Debug: Found date via Latest updates section: {most_recent.date()}")
                    return most_recent.date()
        
        # Fallback to time elements
        time_elements = soup.find_all('time')
        if time_elements:
            valid_dates = []
            for time_elem in time_elements:
                datetime_attr = time_elem.get('datetime')
                if datetime_attr:
                    try:
                        dt = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                        valid_dates.append(dt)
                    except ValueError:
                        # Try parsing text content
                        text_content = time_elem.get_text().strip()
                        for date_format in ['%b %d, %Y', '%B %d, %Y', '%m/%d/%Y']:
                            try:
                                dt = datetime.strptime(text_content, date_format)
                                valid_dates.append(dt)
                                break
                            except ValueError:
                                continue
            
            if valid_dates:
                most_recent = max(valid_dates)
                print(f"Debug: Found date via time elements: {most_recent.date()}")
                return most_recent.date()
        
        # No valid dates found
        return date.today() - timedelta(days=1)

    def has_new_cheats(self, database_version):
        return self.gbatemp_version > database_version

    def get_gbatemp_version(self):
        return self.gbatemp_version

    def get_custom_proxy(self):
        """Get custom proxy from environment variable with Squid proxy optimizations"""
        custom_proxy_url = os.environ.get('CUSTOM_PROXY_URL')
        if custom_proxy_url:
            # For Squid proxies, ensure proper format
            if not custom_proxy_url.startswith(('http://', 'https://')):
                custom_proxy_url = f"http://{custom_proxy_url}"
            
            proxy_config = {'http': custom_proxy_url, 'https': custom_proxy_url}
            return proxy_config
        return None
    
    def validate_proxy(self, proxy, timeout=8):
        """Test if a proxy is working by making a test request"""
        try:
            # Try multiple test endpoints for better validation
            test_urls = [
                'https://httpbin.org/ip',
                'https://api.ipify.org?format=json', 
                'https://ifconfig.me/ip',
                'https://gbatemp.net/',  # Test the actual target domain
            ]
            
            success_count = 0
            
            for i, test_url in enumerate(test_urls):
                try:
                    # Squid proxy optimized headers
                    squid_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
                        'Accept': '*/*',
                        'Accept-Encoding': 'identity',  # Squid sometimes has issues with compression
                        'Connection': 'close',  # Avoid keep-alive issues
                        'Cache-Control': 'no-cache'
                    }
                    
                    # For GBATemp, try with longer timeout since it's the target domain
                    test_timeout = timeout * 2 if 'gbatemp.net' in test_url else timeout
                    
                    test_response = requests.get(
                        test_url,
                        proxies=proxy,
                        timeout=test_timeout,
                        headers=squid_headers,
                        allow_redirects=True
                    )
                    
                    if test_response.status_code == 200:
                        success_count += 1
                        
                        # If GBATemp works, that's what we really need
                        if 'gbatemp.net' in test_url:
                            return True
                            
                except requests.exceptions.ProxyError as e:
                    # Check for specific proxy issues
                    if 'Authentication required' in str(e) or 'Proxy Authentication Required' in str(e):
                        print("Proxy authentication required - check Squid configuration")
                    elif 'Connection refused' in str(e):
                        print("Proxy connection refused - check Squid is running")
                    continue
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError, 
                        requests.exceptions.Timeout):
                    continue
                except Exception:
                    continue
                    
            # Smart proxy validation logic
            if success_count >= 2:
                return True
            elif success_count == 1:
                # Proceed with partial functionality
                return True
            else:
                print("All proxy test URLs failed")
                return False
        except Exception:
            return False
    
    def get_working_proxy(self):
        """Get the custom proxy if available and valid"""
        custom_proxy = self.get_custom_proxy()
        if custom_proxy and self.validate_proxy(custom_proxy, timeout=10):
            return custom_proxy
        return None

    def establish_session(self):
        """Establish session with advanced cloudscraper techniques"""
        try:
            print("  Establishing session with advanced bypass...")
            
            # Create a fresh cloudscraper with more aggressive settings
            fresh_scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                },
                delay=3,  # Balanced delay
                debug=False
            )
            
            # Updated headers with latest Chrome version and additional headers
            fresh_scraper.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'max-age=0',
                'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Connection': 'keep-alive'
            })
            
            # Test multiple approaches with more realistic browsing behavior
            test_strategies = [
                ("Direct HTTPS", "https://gbatemp.net/"),
                ("WWW subdomain", "https://www.gbatemp.net/"),
            ]
            
            for strategy_name, base_url in test_strategies:
                try:
                    print(f"  Trying {strategy_name}: {base_url}")
                    
                    # Simulate more realistic browsing - visit homepage first
                    time.sleep(2)
                    response = fresh_scraper.get(base_url, timeout=30, allow_redirects=True)
                    
                    if response.status_code == 200:
                        # Check if we got a valid page (not blocked)
                        content_lower = response.content.lower()
                        if b'gbatemp' in content_lower or b'community' in content_lower:
                            print(f"  SUCCESS with {strategy_name}")
                            # Update our main scraper
                            self.scraper = fresh_scraper
                            self.working_base = base_url.rstrip('/')
                            
                            # Now try to navigate to the downloads section to warm up the session
                            try:
                                time.sleep(2)
                                downloads_url = f"{self.working_base}/downloads/"
                                downloads_response = fresh_scraper.get(downloads_url, timeout=30)
                                if downloads_response.status_code == 200:
                                    print(f"  Session warmed up successfully")
                                else:
                                    print(f"  Warning: Downloads page returned {downloads_response.status_code}")
                            except Exception:
                                print(f"  Warning: Could not warm up session with downloads page")
                            
                            return True
                        else:
                            print(f"  {strategy_name} returned blocked content (possible captcha)")
                    else:
                        print(f"  {strategy_name} returned {response.status_code}")
                        
                except Exception as e:
                    print(f"  {strategy_name} failed: {type(e).__name__}: {e}")
                    continue
            
            print("  All session strategies failed")
            return False
            
        except Exception as e:
            print(f"  Session establishment error: {e}")
            return False

    def get_download_url(self):
        return f"{self.page_url.rstrip('/')}/download"


class HighFPSCheatsInfo:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.download_url = "https://github.com/ChanseyIsTheBest/NX-60FPS-RES-GFX-Cheats/archive/refs/heads/main.zip"
        self.api_url = "https://api.github.com/repos/ChanseyIsTheBest/NX-60FPS-RES-GFX-Cheats/branches/main"
        self.highfps_version = self.fetch_high_FPS_cheats_version()

    def fetch_high_FPS_cheats_version(self):
        try:
            token = os.getenv('GITHUB_TOKEN')
            headers = {'Authorization': f'token {token}'} if token else {}
            repo_info = self.scraper.get(self.api_url, headers=headers).json()
            
            if 'commit' not in repo_info:
                print("Warning: Could not fetch GitHub API data for high FPS cheats, using fallback date")
                return date.today() - timedelta(days=1)
            
            last_commit_date = repo_info.get("commit").get("commit").get("author").get("date")
            return date.fromisoformat(last_commit_date.split("T")[0])
        except Exception as e:
            print(f"Error fetching high FPS cheats version: {e}")
            print("Using fallback date to force update")
            return date.today() - timedelta(days=1)

    def has_new_cheats(self, database_version):
        return self.highfps_version > database_version

    def get_high_FPS_version(self):
        return self.highfps_version

    def get_download_url(self):
        return self.download_url


class ArchiveWorker():
    def __init__(self):
        # Use the same improved scraper configuration with enhanced headers
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=10
        )
        self.scraper.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        })

    def download_with_browser(self, url, path, timeout=120):
        """Download using a real browser with Playwright to bypass bot protection"""
        if not PLAYWRIGHT_AVAILABLE:
            raise Exception("Playwright not available - cannot use browser download method")
        
        print(f"  Using real browser to download from: {url}")
        
        # Detect if we're running in CI environment
        is_ci = any(env_var in os.environ for env_var in ['CI', 'GITHUB_ACTIONS', 'RUNNER_OS'])
        if is_ci:
            print(f"  Detected CI environment, using CI-optimized settings")
        
        try:
            with sync_playwright() as p:
                # Configure browser args based on environment
                browser_args = [
                    '--no-blink-features=AutomationControlled',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                ]
                
                if is_ci:
                    # Add additional CI-specific args
                    browser_args.extend([
                        '--disable-gpu',
                        '--disable-software-rasterizer',
                        '--disable-extensions',
                        '--disable-plugins',
                        '--single-process',
                        '--no-zygote',
                        '--disable-background-networking'
                    ])
                
                # Launch browser with environment-specific settings
                browser = p.chromium.launch(
                    headless=True,
                    args=browser_args
                )
                
                # Create a new page with the latest user agent
                page = browser.new_page(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                # Set realistic viewport
                page.set_viewport_size({'width': 1920, 'height': 1080})
                
                # Add more comprehensive realistic headers
                page.set_extra_http_headers({
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Cache-Control': 'max-age=0',
                    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1'
                })
                
                # First visit the main page to establish session and cookies
                print(f"  Establishing session by visiting main page...")
                try:
                    main_url = "https://gbatemp.net/"
                    page.goto(main_url, wait_until='networkidle', timeout=30000)
                    print(f"  Main page loaded successfully")
                    
                    # Simulate human behavior - scroll and wait
                    page.wait_for_timeout(2000)
                    page.evaluate('window.scrollTo(0, 100)')
                    page.wait_for_timeout(1000)
                    
                    # Visit the downloads section to establish proper session
                    try:
                        downloads_url = "https://gbatemp.net/downloads/"
                        page.goto(downloads_url, wait_until='networkidle', timeout=30000)
                        print(f"  Downloads page loaded successfully")
                        page.wait_for_timeout(1500)
                        
                        # Scroll to simulate browsing
                        page.evaluate('window.scrollTo(0, 200)')
                        page.wait_for_timeout(1000)
                    except Exception as e:
                        print(f"  Could not navigate to downloads page: {e}")
                    
                except Exception as e:
                    print(f"  Warning: Could not navigate main page: {e}")
                
                # Now navigate to the specific download URL
                print(f"  Navigating to download URL...")
                
                # Set up download handling
                download_info = {'path': None, 'error': None}
                
                def handle_download(download):
                    try:
                        print(f"  Download started: {download.url}")
                        download.save_as(path)
                        download_info['path'] = path
                        print(f"  Download saved to: {path}")
                    except Exception as e:
                        download_info['error'] = str(e)
                        print(f"  Download error: {e}")
                
                page.on('download', handle_download)
                
                # Navigate to the download URL with realistic behavior
                try:
                    # Add small delay to simulate human clicking
                    page.wait_for_timeout(1000)
                    
                    print(f"  Navigating to download URL with realistic timing...")
                    response = page.goto(url, wait_until='networkidle', timeout=timeout * 1000)
                    
                    # Simulate human behavior - small wait after page load
                    page.wait_for_timeout(2000)
                    
                except Exception as e:
                    # Check if the exception is due to download starting (this is actually success)
                    if "Download is starting" in str(e) or "net::ERR_ABORTED" in str(e):
                        print(f"  Download started automatically")
                        # Wait for download to complete with longer timeout
                        page.wait_for_timeout(20000)  # Wait up to 20 seconds for download
                        
                        if download_info['path']:
                            print(f"  Download completed successfully")
                            browser.close()
                            return
                        elif download_info['error']:
                            browser.close()
                            raise Exception(f"Download failed: {download_info['error']}")
                        else:
                            # Download might still be in progress, wait longer
                            print(f"  Waiting longer for download completion...")
                            page.wait_for_timeout(15000)
                            if download_info['path']:
                                print(f"  Download completed after additional wait")
                                browser.close()
                                return
                            else:
                                raise Exception("Download started but did not complete")
                    else:
                        raise e
                
                if response:
                    print(f"  Response status: {response.status}")
                    
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.status_text}")
                
                # Wait for potential download or check if we're on a download page
                page.wait_for_timeout(3000)
                
                # Check if download was triggered automatically
                if download_info['path']:
                    print(f"  Automatic download completed")
                    browser.close()
                    return
                
                if download_info['error']:
                    browser.close()
                    raise Exception(f"Download failed: {download_info['error']}")
                
                # If no automatic download, check page content
                content_type = response.headers.get('content-type', '').lower()
                print(f"  Content-Type: {content_type}")
                
                if 'text/html' in content_type:
                    # We're on an HTML page, look for download links
                    print(f"  Looking for download links on page...")
                    
                    # Try GBATemp-specific and common download button selectors
                    download_selectors = [
                        'a[href*="download"]',
                        'a.button[href*="download"]',
                        '.downloadButton',
                        '.download',
                        '[download]',
                        'a[href$=".rar"]',
                        'a[href$=".zip"]',
                        'a[title*="Download"]',
                        'button:has-text("Download")',
                        'a:has-text("Download")'
                    ]
                    
                    for selector in download_selectors:
                        try:
                            download_links = page.locator(selector)
                            count = download_links.count()
                            if count > 0:
                                print(f"  Found {count} potential download links with selector: {selector}")
                                # Click the first viable download link
                                download_links.first.click()
                                
                                # Wait for download to start
                                page.wait_for_timeout(5000)
                                
                                if download_info['path']:
                                    print(f"  Download completed via link click")
                                    browser.close()
                                    return
                        except Exception as e:
                            continue
                    
                    # If still no download, the page might contain the file directly
                    print(f"  No download links found, checking if page contains file data...")
                    
                    # Check if this might be a direct file response disguised as HTML
                    page_content = page.content()
                    if len(page_content) > 1000000 and 'Rar!' in page_content[:1000]:  # Large content with RAR signature
                        print(f"  Page appears to contain RAR data directly")
                        with open(path, 'wb') as f:
                            f.write(page_content.encode('latin1'))  # Preserve binary data
                        browser.close()
                        return
                
                else:
                    # Direct file response
                    print(f"  Direct file response detected")
                    # The page should have triggered a download already, wait a bit more
                    page.wait_for_timeout(10000)
                    
                    if not download_info['path']:
                        # Try to get the response body directly
                        body = response.body()
                        with open(path, 'wb') as f:
                            f.write(body)
                        print(f"  Saved response body directly ({len(body)} bytes)")
                
                browser.close()
                
                # Verify the file was created and has reasonable size
                if os.path.exists(path):
                    file_size = os.path.getsize(path)
                    print(f"  Final file size: {file_size} bytes")
                    if file_size < 1000:
                        raise Exception(f"Downloaded file is too small ({file_size} bytes)")
                else:
                    raise Exception("Download completed but file not found")
                    
        except Exception as e:
            print(f"  Browser download failed: {e}")
            raise

    def download_gbatemp_archive(self, gbatemp_info, url, path):
        """Streamlined GBATemp download using only custom proxy"""
        print(f"  Attempting GBATemp download from: {url}")
        
        # Get custom proxy - this is the only strategy now
        custom_proxy = gbatemp_info.get_custom_proxy()
        if not custom_proxy:
            print(f"  No custom proxy available - download not possible")
            raise Exception("Custom proxy required for GBATemp downloads")
        
        if not gbatemp_info.validate_proxy(custom_proxy, timeout=10):
            print(f"  Custom proxy validation failed - download not possible")
            raise Exception("Custom proxy validation failed")
        
        print(f"  Using custom proxy for download...")
        
        try:
            # Create scraper with custom proxy
            proxy_scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                delay=3
            )
            
            proxy_scraper.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/octet-stream,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
            })
            
            proxy_scraper.proxies.update(custom_proxy)
            
            print(f"  Starting download through custom proxy...")
            try:
                response = proxy_scraper.get(url, timeout=120, stream=True)
            except requests.exceptions.ConnectTimeout:
                raise Exception("Proxy connection timeout - check proxy configuration")
            except requests.exceptions.ProxyError as e:
                if 'Authentication' in str(e):
                    raise Exception("Proxy authentication required")
                elif 'Connection refused' in str(e):
                    raise Exception("Proxy connection refused - check if proxy is running")
                else:
                    raise Exception("Proxy error occurred")
            except Exception as e:
                raise Exception(f"Download failed: {type(e).__name__}")
            
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                print(f"  Download size: {total_size // (1024*1024)}MB")
                
                with open(path, 'wb') as f:
                    downloaded = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                if downloaded % (1024*1024*10) == 0:  # Log every 10MB
                                    print(f"  Downloaded: {percent:.1f}%")
                
                # Verify download
                if os.path.exists(path) and os.path.getsize(path) > 1024*1024:  # At least 1MB
                    print(f"  Download completed successfully: {os.path.getsize(path) // (1024*1024)}MB")
                    return
                else:
                    print(f"  Download verification failed - file too small or missing")
                    raise Exception("Downloaded file is invalid")
            elif response.status_code == 403:
                print(f"  Download failed: HTTP 403 Forbidden")
                print(f"  GBATemp is blocking proxy access - this is a website restriction, not a proxy issue")
                print(f"  Proxy configuration is working correctly (validated with other sites)")
                raise Exception("GBATemp blocks proxy access (HTTP 403) - website policy restriction")
            else:
                print(f"  Download failed with status: {response.status_code}")
                if response.status_code in [503, 502, 504]:
                    print(f"  Server error - may be temporary GBATemp issue")
                elif response.status_code == 429:
                    print(f"  Rate limited - too many requests to GBATemp")
                raise Exception(f"HTTP {response.status_code}")
                
        except Exception as e:
            print(f"  Custom proxy download failed: {e}")
            raise Exception("Custom proxy download failed")
    
    def _download_with_session(self, gbatemp_info, url, path):
        """Primary download strategy with session establishment"""
        # Establish session first
        if not gbatemp_info.establish_session():
            raise Exception("Failed to establish session with GBATemp")
        
        # Use the established session from gbatemp_info
        scraper = gbatemp_info.scraper
        
        # Navigate to the download page first (simulate realistic browsing)
        try:
            print(f"  Navigating to download page...")
            time.sleep(3)
            
            # Visit the main page first
            main_page_response = scraper.get(gbatemp_info.page_url, timeout=30, allow_redirects=True)
            if main_page_response.status_code != 200:
                print(f"  Warning: Main page returned {main_page_response.status_code}")
            
            time.sleep(2)
            
            # Update headers for the actual download
            scraper.headers.update({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Referer': gbatemp_info.page_url,
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
            })
            
            print(f"  Attempting download...")
            # Try the download with the established session
            dl = scraper.get(url, allow_redirects=True, timeout=90, stream=True)
            
            # Check response
            if dl.status_code != 200:
                raise Exception(f"HTTP {dl.status_code}: {dl.reason}")
            
            # Validate content
            self._validate_and_save_archive(dl, path)
            
        except Exception as e:
            print(f"  Session download failed: {e}")
            raise
        
    def _download_with_alternative_headers(self, url, path):
        """Alternative download strategy with different headers"""
        print("  Trying alternative headers strategy...")
        
        # Try multiple different browser configurations
        alt_configs = [
            {
                'name': 'Firefox Windows',
                'browser': {'browser': 'firefox', 'platform': 'windows', 'desktop': True},
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                }
            },
            {
                'name': 'Edge Windows',
                'browser': {'browser': 'chrome', 'platform': 'windows', 'desktop': True},
                'headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Sec-Ch-Ua': '"Microsoft Edge";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                }
            }
        ]
        
        for config in alt_configs:
            try:
                print(f"  Trying {config['name']}...")
                
                alt_scraper = cloudscraper.create_scraper(
                    browser=config['browser'],
                    delay=2
                )
                alt_scraper.headers.update(config['headers'])
                
                time.sleep(3)
                dl = alt_scraper.get(url, allow_redirects=True, timeout=60)
                
                if dl.status_code == 200:
                    self._validate_and_save_archive(dl, path)
                    print(f"  Success with {config['name']}")
                    return
                else:
                    print(f"  {config['name']} returned {dl.status_code}")
                    
            except Exception as e:
                print(f"  {config['name']} failed: {e}")
                continue
        
        raise Exception("All alternative header strategies failed")
        

    def _download_with_time_delays(self, url, path):
        """Try download with various timing patterns to evade rate limiting"""
        print(f"  Trying time-delayed approaches...")
        
        # Different timing patterns to try
        timing_strategies = [
            {"name": "Long delay", "initial_delay": 30, "retry_delay": 45},
            {"name": "Random intervals", "initial_delay": 15, "retry_delay": 25},
            {"name": "Gradual escalation", "initial_delay": 10, "retry_delay": 60},
        ]
        
        for strategy in timing_strategies:
            try:
                print(f"  Trying {strategy['name']} (waiting {strategy['initial_delay']}s)...")
                time.sleep(strategy['initial_delay'])
                
                # Create a fresh scraper for each attempt
                scraper = cloudscraper.create_scraper(
                    browser={'browser': 'chrome', 'platform': 'linux', 'mobile': False},
                    delay=3
                )
                
                # Set realistic headers
                scraper.headers.update({
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                })
                
                # Try the download
                response = scraper.get(url, timeout=90, allow_redirects=True)
                
                if response.status_code == 200:
                    self._validate_and_save_archive(response, path)
                    print(f"  Success with {strategy['name']} strategy!")
                    return
                else:
                    print(f"  {strategy['name']} returned {response.status_code}")
                    time.sleep(strategy['retry_delay'])
                    
            except Exception as e:
                print(f"  {strategy['name']} failed: {e}")
                continue
        
        raise Exception("All timing strategies failed")
    
    def _download_with_wget(self, url, path):
        """Download using wget in CI environments as a last resort"""
        print(f"  Trying wget download (CI environment)...")
        
        import subprocess
        import shutil
        
        # Check if wget is available
        if not shutil.which('wget'):
            raise Exception("wget not available")
        
        try:
            # Use wget with realistic headers to mimic browser behavior
            wget_cmd = [
                'wget',
                '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--header=Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                '--header=Accept-Language: en-US,en;q=0.5',
                '--header=Accept-Encoding: gzip, deflate',
                '--header=Connection: keep-alive',
                '--header=Upgrade-Insecure-Requests: 1',
                '--timeout=60',
                '--tries=2',
                '--wait=3',
                '--random-wait',
                '--no-check-certificate',
                '-O', path,
                url
            ]
            
            result = subprocess.run(wget_cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                raise Exception(f"wget failed with code {result.returncode}: {result.stderr}")
            
            # Check if file was actually created and has reasonable size
            if not os.path.exists(path):
                raise Exception("wget completed but no file was created")
            
            file_size = os.path.getsize(path)
            if file_size < 1000000:  # Less than 1MB is suspicious for GBATemp cheats
                raise Exception(f"Downloaded file is too small ({file_size} bytes) - likely bot protection")
            
            print(f"  wget download successful: {file_size} bytes")
            return
            
        except subprocess.TimeoutExpired:
            raise Exception("wget download timed out")
        except Exception as e:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
            raise Exception(f"wget download failed: {e}")
        
    def _validate_and_save_archive(self, response, path):
        """Validate and save archive content"""
        content_type = response.headers.get('content-type', '').lower()
        content_length = len(response.content)
        
        print(f"  Response: {response.status_code}, Content-Type: {content_type}, Size: {content_length} bytes")
        
        # Detect if we got HTML instead of an archive
        if 'text/html' in content_type or content_length < 1000:
            # Save response for debugging
            debug_file = path + f'.debug_{response.status_code}.html'
            with open(debug_file, 'wb') as f:
                f.write(response.content)
            
            if b'<html' in response.content[:500].lower():
                if b'captcha' in response.content.lower() or b'cloudflare' in response.content.lower():
                    raise Exception("Bot protection detected - received captcha/cloudflare page")
                elif b'forbidden' in response.content.lower() or b'403' in response.content:
                    raise Exception("Access forbidden - IP might be blocked")
                else:
                    raise Exception(f"Received HTML page instead of archive (saved to {debug_file})")
            else:
                raise Exception(f"Invalid content received - too small or wrong type (saved to {debug_file})")

        # Additional validation for RAR files
        if path.endswith('.rar'):
            # Check RAR signature and basic structure
            if not response.content.startswith(b'Rar!'):
                raise Exception("Invalid RAR file - missing signature")
            
            # For GBATemp, we expect a reasonable file size (at least 2MB)
            if content_length < 2000000:  # 2MB minimum
                print(f"  Warning: RAR file seems small ({content_length} bytes)")
            
            # Check for suspicious patterns that might indicate blocked content
            suspicious_patterns = [
                b'access denied',
                b'blocked',
                b'security check',
                b'please wait',
                b'checking your browser',
                b'ddos protection',
            ]
            
            content_lower = response.content.lower()
            for pattern in suspicious_patterns:
                if pattern in content_lower:
                    raise Exception(f"Suspicious content detected - possible bot protection: '{pattern.decode()}'")

        # Write the archive
        with open(path, 'wb') as f:
            f.write(response.content)
        
        print(f"  Successfully downloaded {content_length} bytes to {path}")
        
        # Post-download validation for RAR files
        if path.endswith('.rar'):
            try:
                # Quick test to see if rarfile can at least open it and read content
                import rarfile
                with rarfile.RarFile(path) as rf:
                    file_list = rf.namelist()
                    print(f"  RAR validation: {len(file_list)} files listed")
                    
                    if len(file_list) < 100:  # GBATemp cheats should have many more files
                        print(f"  Warning: RAR contains unusually few files ({len(file_list)})")
                    
                    # Test integrity by reading a few files
                    test_files = file_list[:3] if file_list else []
                    corruption_detected = False
                    
                    for test_file in test_files:
                        try:
                            data = rf.read(test_file)
                            if len(data) < 100:  # Most cheat files should be larger
                                print(f"  Warning: {test_file} is unusually small ({len(data)} bytes)")
                        except Exception as e:
                            if "Failed the read enough data" in str(e) and "got=51" in str(e):
                                corruption_detected = True
                                print(f"  ✗ Corruption detected: {e}")
                                break
                            else:
                                print(f"  Warning: Could not read {test_file}: {e}")
                    
                    if corruption_detected:
                        raise Exception("RAR file appears corrupted - likely due to GBATemp bot protection")
                        
            except Exception as e:
                error_msg = str(e)
                if "Failed the read enough data" in error_msg or "corrupted" in error_msg.lower():
                    print(f"  ✗ RAR corruption detected: {e}")
                    # Remove the corrupted file
                    try:
                        os.remove(path)
                        print(f"  Removed corrupted file: {path}")
                    except:
                        pass
                    raise Exception("GBATemp served corrupted data - likely bot protection")
                else:
                    print(f"  Warning: RAR validation failed: {e}")
                    # Don't fail here for other types of errors

    def _download_with_proxies(self, gbatemp_info, url, path):
        """Try download using free proxies to bypass IP blocking"""
        print(f"  Trying free proxy rotation to bypass IP blocking...")
        
        # Get working proxies
        working_proxies = gbatemp_info.get_working_proxies(max_proxies=3)
        
        if not working_proxies:
            # Try alternative approach: use public proxy services that rotate automatically
            print("  No direct proxies found, trying proxy service APIs...")
            try:
                return self._download_with_proxy_services(url, path)
            except Exception as e:
                print(f"  Proxy services also failed: {e}")
            raise Exception("No working proxies found")
        
        # Try each proxy with different strategies
        for i, proxy in enumerate(working_proxies):
            try:
                # Hide proxy details for security - don't extract actual IP
                proxy_label = f"#{i+1}"
                print(f"  Attempting download via proxy {i+1}/{len(working_proxies)}: [HIDDEN]")
                
                # Strategy 1: cloudscraper with proxy
                try:
                    print(f"    Using cloudscraper with proxy...")
                    proxy_scraper = cloudscraper.create_scraper(
                        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
                        delay=5
                    )
                    
                    # Configure proxy
                    proxy_scraper.proxies.update(proxy)
                    
                    # Set realistic headers
                    proxy_scraper.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'Connection': 'keep-alive',
                        'DNT': '1',
                        'Upgrade-Insecure-Requests': '1'
                    })
                    
                    # Add delay to seem more human
                    time.sleep(random.uniform(5, 10))
                    
                    # Try the download
                    response = proxy_scraper.get(url, timeout=60, allow_redirects=True)
                    
                    if response.status_code == 200:
                        self._validate_and_save_archive(response, path)
                        print(f"  + Success with proxy {proxy_label}!")
                        return
                    else:
                        print(f"    Proxy {proxy_label} returned {response.status_code}")
                
                except Exception as e:
                    print(f"    cloudscraper with proxy {proxy_label} failed: {e}")
                
                # Strategy 2: Plain requests with proxy
                try:
                    print(f"    Using plain requests with proxy...")
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Connection': 'keep-alive'
                    }
                    
                    time.sleep(random.uniform(3, 8))
                    
                    response = requests.get(url, proxies=proxy, headers=headers, timeout=45, allow_redirects=True)
                    
                    if response.status_code == 200:
                        self._validate_and_save_archive(response, path)
                        print(f"  + Success with requests + proxy {proxy_label}!")
                        return
                    else:
                        print(f"    Plain requests with proxy {proxy_label} returned {response.status_code}")
                
                except Exception as e:
                    print(f"    Plain requests with proxy {proxy_label} failed: {e}")
                
            except Exception as e:
                print(f"  Proxy {proxy_label} failed completely: {e}")
                continue
        
        raise Exception(f"All {len(working_proxies)} proxies failed")

    def _download_with_proxy_services(self, url, path):
        """Try download using proxy service APIs that handle rotation automatically"""
        print("  Attempting download via proxy service APIs...")
        
        # Service 1: Try with different geographic endpoints that might not be blocked
        geo_endpoints = [
            'https://proxy.toolforge.org/',  # Wikimedia proxy
            'https://cors-anywhere.herokuapp.com/',  # CORS proxy
        ]
        
        for i, proxy_service in enumerate(geo_endpoints):
            try:
                print(f"  Trying proxy service {i+1}: {proxy_service}")
                
                # Construct proxied URL
                proxied_url = proxy_service + url
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive'
                }
                
                response = requests.get(proxied_url, headers=headers, timeout=45, allow_redirects=True)
                
                if response.status_code == 200:
                    self._validate_and_save_archive(response, path)
                    print(f"  + Success with proxy service {proxy_service}!")
                    return
                else:
                    print(f"  Proxy service returned {response.status_code}")
                    
            except Exception as e:
                print(f"  Proxy service {proxy_service} failed: {e}")
                continue
        
        raise Exception("All proxy services failed")

    def download_archive(self, url, path):
        print(f"  Attempting download from: {url}")
        
        # Add a small delay to be respectful to servers
        time.sleep(2)
        
        # Try the download with timeout
        try:
            dl = self.scraper.get(url, allow_redirects=True, timeout=30)
        except Exception as e:
            raise Exception(f"Download failed: {e}")
        
        # Check if we got a valid response
        if dl.status_code != 200:
            raise Exception(f"HTTP {dl.status_code}: {dl.reason}")
        
        # Check content type and size
        content_type = dl.headers.get('content-type', '').lower()
        content_length = len(dl.content)
        
        print(f"  Response: {dl.status_code}, Content-Type: {content_type}, Size: {content_length} bytes")
        
        # Detect if we got HTML instead of an archive (likely captcha/bot protection)
        if 'text/html' in content_type or content_length < 1000:
            print(f"  Warning: Received HTML response (likely bot protection)")
            if b'<html' in dl.content[:500].lower() or b'captcha' in dl.content.lower():
                print(f"  Detected HTML/captcha page instead of archive")
                # Still write the file for debugging
                with open(path + '.html', 'wb') as f:
                    f.write(dl.content)
                raise Exception("Bot protection detected - received HTML page instead of archive")
        
        # Check if content looks like an archive and detect format
        archive_info = {
            b'PK': ('ZIP', '.zip'),
            b'Rar!': ('RAR', '.rar'), 
            b'\x1f\x8b': ('GZIP', '.gz'),
        }
        
        detected_format = None
        detected_extension = None
        for signature, (format_name, extension) in archive_info.items():
            if dl.content.startswith(signature):
                detected_format = format_name
                detected_extension = extension
                break
        
        if detected_format:
            print(f"  Detected {detected_format} archive")
            # If the path has wrong extension, suggest the correct one
            if not path.endswith(detected_extension):
                correct_path = path.rsplit('.', 1)[0] + detected_extension
                print(f"  Note: Archive is {detected_format} but path suggests different format")
                print(f"  Consider using: {correct_path}")
        else:
            if content_length > 100:
                print(f"  Warning: Content doesn't appear to be a valid archive")
                print(f"  First 100 bytes: {dl.content[:100]}")
        
        with open(path, "wb") as f:
            f.write(dl.content)
        
        print(f"  ✓ Downloaded {content_length} bytes to {path}")

    def extract_archive(self, path, extract_path=None):
        try:
            # First try to detect the archive type by file signature
            with open(path, 'rb') as f:
                signature = f.read(10)
            
            # Check for RAR signature
            if signature.startswith(b'Rar!'):
                print(f"  Detected RAR archive")
                try:
                    rf = rarfile.RarFile(path)
                    rf.extractall(path=extract_path)
                    print(f"  RAR extraction completed successfully")
                    return True
                except Exception as e:
                    print(f"  RAR extraction failed: {e}")
                    # Try alternative RAR handling or conversion
                    return self._try_alternative_extraction(path, extract_path, 'rar')
                    
            # Check for ZIP signature  
            elif signature.startswith(b'PK'):
                print(f"  Detected ZIP archive")
                try:
                    zf = zipfile.ZipFile(path)
                    zf.extractall(path=extract_path)
                    print(f"  ZIP extraction completed successfully")
                    return True
                except Exception as e:
                    print(f"  ZIP extraction failed: {e}")
                    return False
                    
            else:
                print(f"  Unknown archive format - signature: {signature[:4].hex()}")
                # Try both methods anyway
                try:
                    if rarfile.is_rarfile(path):
                        rf = rarfile.RarFile(path)
                        rf.extractall(path=extract_path)
                        return True
                except:
                    pass
                    
                try:
                    if zipfile.is_zipfile(path):
                        zf = zipfile.ZipFile(path)
                        zf.extractall(path=extract_path)
                        return True
                except:
                    pass
                    
                return False
                
        except Exception as e:
            print(f"  Archive extraction error: {e}")
            return False
    
    def _try_alternative_extraction(self, path, extract_path, archive_type):
        """Try alternative extraction methods for problematic archives"""
        print(f"  Trying alternative extraction for {archive_type} archive...")
        
        if archive_type == 'rar':
            try:
                # Try with different RAR options
                rf = rarfile.RarFile(path)
                
                # List contents first to check if readable
                file_list = rf.namelist()
                print(f"  Archive contains {len(file_list)} files")
                
                # Extract with error handling for each file
                extracted_count = 0
                for file_info in rf.infolist():
                    try:
                        rf.extract(file_info, path=extract_path)
                        extracted_count += 1
                    except Exception as e:
                        print(f"  Warning: Could not extract {file_info.filename}: {e}")
                        continue
                
                print(f"  Successfully extracted {extracted_count}/{len(file_list)} files")
                return extracted_count > 0
                
            except Exception as e:
                print(f"  Alternative RAR extraction failed: {e}")
                return False
        
        return False

    def build_cheat_files(self, cheats_path, out_path):
        cheats_path = Path(cheats_path)
        titles_path = Path(out_path).joinpath("titles")
        if not(titles_path.exists()):
            titles_path.mkdir(parents=True)
        for tid in cheats_path.iterdir():
            tid_path = titles_path.joinpath(tid.stem)
            tid_path.mkdir(exist_ok=True)
            with open(tid, "r", encoding="utf-8", errors="ignore") as cheats_file:
                cheats_dict = json.load(cheats_file)
            for key, value in cheats_dict.items():
                if key == "attribution":
                    for author, content in value.items():
                        with open(tid_path.joinpath(author), "w", encoding="utf-8") as attribution_file:
                            attribution_file.write(content)
                else:
                    cheats_folder = tid_path.joinpath("cheats")
                    cheats_folder.mkdir(exist_ok=True)
                    cheats = ""
                    for _, content in value.items():
                        cheats += content
                    if cheats:
                        with open(cheats_folder.joinpath(f"{key}.txt"), "w", encoding="utf-8") as bid_file:
                            bid_file.write(cheats)

    def touch_all(self, path):
        for path in path.rglob("*"):
            if path.is_file():
                path.touch()

    def create_archives(self, out_path):
        out_path = Path(out_path)
        titles_path = out_path.joinpath("titles")
        
        if not titles_path.exists():
            print(f"Warning: {titles_path} does not exist, cannot create archives")
            return False
            
        self.touch_all(titles_path)
        titles_zip = f"{titles_path.resolve()}.zip"
        shutil.make_archive(str(titles_path.resolve()), "zip", root_dir=out_path, base_dir="titles")
        print(f"Created: {titles_zip}")
        
        # Handle the rename more carefully - remove existing contents dir first
        contents_path = titles_path.parent.joinpath("contents")
        if contents_path.exists():
            shutil.rmtree(contents_path)
        
        contents_path = titles_path.rename(contents_path)
        self.touch_all(contents_path)
        contents_zip = f"{contents_path.resolve()}.zip"
        shutil.make_archive(str(contents_path.resolve()), "zip", root_dir=out_path, base_dir="contents")
        print(f"Created: {contents_zip}")
        
        return True

    def create_version_file(self, out_path=".", version_date=None):
        # Use the provided version date, or fall back to today's date
        actual_date = version_date if version_date else date.today()
        with open(f"{out_path}/VERSION", "w") as version_file:
            version_file.write(str(actual_date))

def count_cheats(cheats_directory):
    n_games = 0
    n_updates = 0
    n_cheats = 0
    for json_file in Path(cheats_directory).glob('*.json'):
        with open(json_file, 'r', encoding="utf-8", errors="ignore") as file:
            cheats = json.load(file)
            for bid in cheats.values():
                n_cheats += len(bid)
                n_updates += 1
        n_games += 1

    readme_file = Path('README.md')
    with readme_file.open('r', encoding="utf-8", errors="ignore") as file:
        lines = file.readlines()
    lines[-1] = f"{n_cheats} cheats in {n_games} titles/{n_updates} updates"
    with readme_file.open('w', encoding="utf-8") as file:
        file.writelines(lines)

if __name__ == '__main__':
    try:
        cheats_path = "cheats"
        cheats_gba_path = "cheats_gbatemp"
        cheats_gfx_path = "cheats_gfx"
        gbatemp_archive_path = "gbatemp_titles.rar"
        highfps_archive_path = "highfps_titles.zip"
        
        print("Initializing database info...")
        database = DatabaseInfo()
        database_version = database.get_database_version()
        
        print("Initializing cheat sources...")
        highfps = HighFPSCheatsInfo()
        gbatemp = GbatempCheatsInfo()
    except Exception as e:
        print(f"Error during initialization: {e}")
        print("Continuing with fallback behavior...")
        database_version = date.today() - timedelta(days=2)  # Force update
        highfps = None
        gbatemp = None
    # Check if we should update (with fallback logic)
    should_update = True  # Default to always update if we can't determine versions
    try:
        if gbatemp and highfps:
            should_update = gbatemp.has_new_cheats(database_version) or highfps.has_new_cheats(database_version)
    except Exception as e:
        print(f"Error checking for updates: {e}. Will proceed with update anyway.")
        should_update = True
    
    if should_update:
        archive_worker = ArchiveWorker()
        print(f"Downloading cheats")
        
        # Download GBATemp cheats (with enhanced session handling)
        gbatemp_success = False
        try:
            print("Downloading GBATemp cheats...")
            if gbatemp:
                print(f"Using GBATemp URL: {gbatemp.get_download_url()}")
                archive_worker.download_gbatemp_archive(gbatemp, gbatemp.get_download_url(), gbatemp_archive_path)
            else:
                # Create temporary gbatemp info for fallback
                gbatemp = GbatempCheatsInfo()
                fallback_url = "https://gbatemp.net/download/cheat-codes-sxos-and-ams-main-cheat-file-updated.36311/download"
                print(f"Using fallback GBATemp URL: {fallback_url}")
                archive_worker.download_gbatemp_archive(gbatemp, fallback_url, gbatemp_archive_path)
            
            print(f"Extracting GBATemp archive to 'gbatemp' directory...")
            extraction_success = archive_worker.extract_archive(gbatemp_archive_path, "gbatemp")
            if extraction_success:
                print("✓ GBATemp archive extracted successfully")
                gbatemp_success = True
            else:
                print("✗ GBATemp archive extraction failed")
                
        except Exception as e:
            print(f"✗ Error downloading/extracting GBATemp cheats: {e}")
            print("  Note: GBATemp has very strict bot protection - this may be temporary")
            print("  Continuing with HighFPS source only...")
        
        # Download HighFPS cheats (with error handling)
        highfps_success = False
        try:
            print("Downloading HighFPS cheats...")
            if highfps:
                print(f"Using HighFPS URL: {highfps.get_download_url()}")
                archive_worker.download_archive(highfps.get_download_url(), highfps_archive_path)
            else:
                fallback_url = "https://github.com/ChanseyIsTheBest/NX-60FPS-RES-GFX-Cheats/archive/refs/heads/main.zip"
                print(f"Using fallback HighFPS URL: {fallback_url}")
                archive_worker.download_archive(fallback_url, highfps_archive_path)
                
            print(f"Extracting HighFPS archive...")
            extraction_success = archive_worker.extract_archive(highfps_archive_path)
            if extraction_success:
                print("✓ HighFPS archive extracted successfully")
                highfps_success = True
            else:
                print("✗ HighFPS archive extraction failed")
                
        except Exception as e:
            print(f"✗ Error downloading/extracting HighFPS cheats: {e}")
        
        # Debug: List what was actually extracted
        print("\nDebug: Checking extracted directories...")
        for check_path in ["gbatemp", "gbatemp/titles", "NX-60FPS-RES-GFX-Cheats-main", "NX-60FPS-RES-GFX-Cheats-main/titles"]:
            path_obj = Path(check_path)
            if path_obj.exists():
                print(f"✓ {check_path} exists")
                if path_obj.is_dir():
                    try:
                        contents = list(path_obj.iterdir())
                        print(f"  Contains {len(contents)} items")
                    except Exception as e:
                        print(f"  Error reading directory: {e}")
            else:
                print(f"✗ {check_path} does not exist")

        print("Processing the cheat sheets")
        
        # Process GBATemp cheats (with directory existence check)
        gbatemp_titles_path = Path("gbatemp/titles")
        if gbatemp_titles_path.exists():
            try:
                print("Processing GBATemp cheats...")
                process_cheats.ProcessCheats("gbatemp/titles", cheats_gba_path)
                process_cheats.ProcessCheats("gbatemp/titles", cheats_path)
                print("✓ GBATemp cheats processed successfully")
            except Exception as e:
                print(f"Error processing GBATemp cheats: {e}")
        else:
            print(f"Note: GBATemp source unavailable - continuing with HighFPS source (525 titles)")
        
        # Process HighFPS cheats (with directory existence check)
        highfps_titles_path = Path("NX-60FPS-RES-GFX-Cheats-main/titles")
        if highfps_titles_path.exists():
            try:
                print("Processing HighFPS cheats...")
                process_cheats.ProcessCheats("NX-60FPS-RES-GFX-Cheats-main/titles", cheats_gfx_path)
                process_cheats.ProcessCheats("NX-60FPS-RES-GFX-Cheats-main/titles", cheats_path)
                print("✓ HighFPS cheats processed successfully")
            except Exception as e:
                print(f"Error processing HighFPS cheats: {e}")
        else:
            print(f"Warning: HighFPS titles directory not found at {highfps_titles_path}")

        # Build complete cheat sheets (only if we have processed cheats)
        cheats_path_obj = Path(cheats_path)
        if cheats_path_obj.exists() and any(cheats_path_obj.iterdir()):
            try:
                print("Building complete cheat sheets...")
                out_path = Path("complete")
                out_path.mkdir(exist_ok=True)
                archive_worker.build_cheat_files(cheats_path, out_path)
                print("✓ Complete cheat sheets built successfully")
            except Exception as e:
                print(f"Error building complete cheat sheets: {e}")
        else:
            print("Warning: No processed cheats found, skipping complete cheat sheets")

        print("Creating the archives")
        
        # Create archives with error handling
        archive_paths = [
            ("complete", "Complete cheats"),
            ("NX-60FPS-RES-GFX-Cheats-main", "HighFPS cheats"),
            ("gbatemp", "GBATemp cheats")
        ]
        
        for archive_path, description in archive_paths:
            if Path(archive_path).exists():
                try:
                    print(f"Creating {description} archive...")
                    success = archive_worker.create_archives(archive_path)
                    if success:
                        print(f"✓ {description} archive created successfully")
                    else:
                        print(f"✗ {description} archive creation failed")
                except Exception as e:
                    print(f"Error creating {description} archive: {e}")
            else:
                print(f"Warning: {description} directory not found, skipping archive creation")

        try:
            # Use the most recent source version date for VERSION file
            version_date = None
            if gbatemp:
                version_date = gbatemp.get_gbatemp_version()
            archive_worker.create_version_file(version_date=version_date)
            print("✓ Version file created successfully")
        except Exception as e:
            print(f"Error creating version file: {e}")

        try:
            if cheats_path_obj.exists():
                count_cheats(cheats_path)
                print("✓ README updated with cheat counts")
            else:
                print("Warning: No cheats directory found, skipping count update")
        except Exception as e:
            print(f"Error updating cheat counts: {e}")

    else:
        print("Everything is already up to date!")
