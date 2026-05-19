import base64
import logging
import asyncio
from github import Github
from config import config

logger = logging.getLogger(__name__)

class GitHubManager:
    def __init__(self):
        self.github = Github(config.GITHUB_TOKEN)
        self.user = self.github.get_user()

    async def create_repo(self, name: str, description: str = ""):
        try:
            repo = self.user.create_repo(name, description=description, private=False, auto_init=True)
            await asyncio.sleep(2)
            return repo
        except Exception as e:
            raise Exception(f"GitHub error: {e}")

    async def push_files(self, repo, files: dict):
        branch = repo.default_branch
        # wait for README to exist
        for _ in range(5):
            try:
                repo.get_contents("README.md", ref=branch)
                break
            except:
                await asyncio.sleep(2)
        for path, content in files.items():
            try:
                repo.create_file(path, f"Add {path}", content, branch=branch)
                logger.info(f"Created {path}")
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Failed {path}: {e}")

    def get_repo_url(self, repo):
        return repo.html_url