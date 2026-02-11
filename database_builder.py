#!/usr/bin/env python3

import rarfile
import zipfile
import json
import shutil
import time
import requests
import re
from pathlib import Path
from datetime import date, datetime, timedelta
import os

import process_cheats


def version_parser(version):
    year = int(version[4:8])
    month = int(version[0:2])
    day = int(version[2:4])
    return date(year, month, day)


class DatabaseInfo:
    def __init__(self):
        self.database_version_url = "https://github.com/exploitz86/switch-cheats-db/releases/latest/download/VERSION"
        self.database_version = self.fetch_database_version()

    def fetch_database_version(self):
        try:
            response = requests.get(self.database_version_url, timeout=30)
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


class GbatempMirrorInfo:
    def __init__(self):
        self.api_url = "https://api.github.com/repos/exploitz86/gbatemp_mirror/releases/latest"
        self.download_url = self._fetch_latest_release_url()

    def _fetch_latest_release_url(self):
        """Fetch the download URL for titles.rar from the latest release"""
        try:
            token = os.getenv('GITHUB_TOKEN')
            headers = {'Authorization': f'token {token}'} if token else {}
            
            print("Fetching GBATemp mirror latest release...")
            response = requests.get(self.api_url, headers=headers, timeout=30)
            release_info = response.json()
            
            if 'assets' not in release_info:
                raise Exception("No assets found in latest release")
            
            # Find titles.rar in the assets
            for asset in release_info['assets']:
                if asset['name'] == 'titles.rar':
                    download_url = asset['browser_download_url']
                    print(f"Found titles.rar in release {release_info['tag_name']}")
                    return download_url
            
            raise Exception("titles.rar not found in release assets")
            
        except Exception as e:
            print(f"Error fetching GBATemp mirror release: {e}")
            raise

    def get_download_url(self):
        return self.download_url


class HighFPSCheatsInfo:
    def __init__(self):
        self.download_url = "https://github.com/ChanseyIsTheBest/NX-60FPS-RES-GFX-Cheats/archive/refs/heads/main.zip"
        self.api_url = "https://api.github.com/repos/ChanseyIsTheBest/NX-60FPS-RES-GFX-Cheats/branches/main"
        self.highfps_version = self.fetch_high_FPS_cheats_version()

    def fetch_high_FPS_cheats_version(self):
        try:
            token = os.getenv('GITHUB_TOKEN')
            headers = {'Authorization': f'token {token}'} if token else {}
            response = requests.get(self.api_url, headers=headers, timeout=30)
            repo_info = response.json()
            
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
        pass

    def download_archive(self, url, path):
        print(f"  Downloading from: {url}")
        
        time.sleep(1)
        
        try:
            token = os.getenv('GITHUB_TOKEN')
            headers = {'Authorization': f'token {token}'} if token else {}
            headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            
            response = requests.get(url, allow_redirects=True, timeout=30, headers=headers)
        except Exception as e:
            raise Exception(f"Download failed: {e}")
        
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code}: {response.reason}")
        
        content_length = len(response.content)
        print(f"  Downloaded {content_length} bytes ({content_length // (1024*1024)}MB)")
        
        with open(path, "wb") as f:
            f.write(response.content)
        
        print(f"  ✓ Saved to {path}")

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
    cheats_path = "cheats"
    cheats_gba_path = "cheats_gbatemp"
    cheats_gfx_path = "cheats_gfx"
    gbatemp_archive_path = "gbatemp_titles.rar"
    highfps_archive_path = "highfps_titles.zip"
    
    print("Initializing database info...")
    database = DatabaseInfo()
    
    print("Initializing cheat sources...")
    highfps = HighFPSCheatsInfo()
    gbatemp = GbatempMirrorInfo()
    
    # Always download - no version checking
    archive_worker = ArchiveWorker()
    print("Downloading cheats")
    
    # Download GBATemp cheats from GitHub mirror
    print("Downloading GBATemp cheats from mirror...")
    print(f"Using GBATemp mirror URL: {gbatemp.get_download_url()}")
    archive_worker.download_archive(gbatemp.get_download_url(), gbatemp_archive_path)
    
    print("Extracting GBATemp archive to 'gbatemp' directory...")
    extraction_success = archive_worker.extract_archive(gbatemp_archive_path, "gbatemp")
    if not extraction_success:
        print("✗ GBATemp archive extraction failed")
        exit(1)
    print("✓ GBATemp archive extracted successfully")
    
    # Download HighFPS cheats
    print("Downloading HighFPS cheats...")
    print(f"Using HighFPS URL: {highfps.get_download_url()}")
    archive_worker.download_archive(highfps.get_download_url(), highfps_archive_path)
    
    print("Extracting HighFPS archive...")
    extraction_success = archive_worker.extract_archive(highfps_archive_path)
    if not extraction_success:
        print("✗ HighFPS archive extraction failed")
        exit(1)
    print("✓ HighFPS archive extracted successfully")
    
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
    
    # Process GBATemp cheats
    gbatemp_titles_path = Path("gbatemp/titles")
    if gbatemp_titles_path.exists():
        print("Processing GBATemp cheats...")
        process_cheats.ProcessCheats("gbatemp/titles", cheats_gba_path)
        process_cheats.ProcessCheats("gbatemp/titles", cheats_path)
        print("✓ GBATemp cheats processed successfully")
    else:
        print("Error: GBATemp titles directory not found")
        exit(1)
    
    # Process HighFPS cheats
    highfps_titles_path = Path("NX-60FPS-RES-GFX-Cheats-main/titles")
    if highfps_titles_path.exists():
        print("Processing HighFPS cheats...")
        process_cheats.ProcessCheats("NX-60FPS-RES-GFX-Cheats-main/titles", cheats_gfx_path)
        process_cheats.ProcessCheats("NX-60FPS-RES-GFX-Cheats-main/titles", cheats_path)
        print("✓ HighFPS cheats processed successfully")
    else:
        print("Error: HighFPS titles directory not found")
        exit(1)

    # Build complete cheat sheets
    cheats_path_obj = Path(cheats_path)
    if cheats_path_obj.exists() and any(cheats_path_obj.iterdir()):
        print("Building complete cheat sheets...")
        out_path = Path("complete")
        out_path.mkdir(exist_ok=True)
        archive_worker.build_cheat_files(cheats_path, out_path)
        print("✓ Complete cheat sheets built successfully")
    else:
        print("Error: No processed cheats found")
        exit(1)

    print("Creating the archives")
    
    # Create archives
    archive_paths = [
        ("complete", "Complete cheats"),
        ("NX-60FPS-RES-GFX-Cheats-main", "HighFPS cheats"),
        ("gbatemp", "GBATemp cheats")
    ]
    
    for archive_path, description in archive_paths:
        if Path(archive_path).exists():
            print(f"Creating {description} archive...")
            success = archive_worker.create_archives(archive_path)
            if not success:
                print(f"✗ {description} archive creation failed")
                exit(1)
            print(f"✓ {description} archive created successfully")
        else:
            print(f"Error: {description} directory not found")
            exit(1)

    # Use the current date for VERSION
    version_date = date.today()
    archive_worker.create_version_file(version_date=version_date)
    print("✓ Version file created successfully")
    
    # Update README with cheat counts
    if cheats_path_obj.exists():
        count_cheats(cheats_path)
        print("✓ README updated with cheat counts")
    else:
        print("Error: No cheats directory found")
        exit(1)
