# Git Setup Guide

## Installing Git on Windows

1. **Download Git for Windows**:
   - Visit: https://git-scm.com/download/win
   - Download the latest version
   - Run the installer

2. **Installation Options** (recommended settings):
   - Use Git from the Windows Command Prompt
   - Use the OpenSSL library
   - Checkout Windows-style, commit Unix-style line endings
   - Use MinTTY (the default terminal of MSYS2)
   - Enable file system caching
   - Enable Git Credential Manager

3. **Verify Installation**:
   ```powershell
   git --version
   ```

## Initial Git Configuration

After installing Git, configure your identity:

```powershell
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## Setting Up This Repository

1. **Initialize the repository**:
   ```powershell
   cd "c:\Users\avibe\OneDrive\Desktop\Coding Projects\Arbitrage"
   git init
   ```

2. **Add all files** (the .gitignore will exclude sensitive files):
   ```powershell
   git add .
   ```

3. **Create your first commit**:
   ```powershell
   git commit -m "Initial commit: Arbitrage opportunity finder"
   ```

## Basic Git Workflow

### Saving Your Work (Committing)

```powershell
# Check what files have changed
git status

# Add specific files
git add filename.py

# Or add all changed files
git add .

# Commit with a descriptive message
git commit -m "Description of changes"
```

### Viewing History

```powershell
# View commit history
git log

# View recent commits (last 5)
git log -n 5

# View changes in a file
git log -p filename.py
```

### Undoing Changes

```powershell
# Discard changes in a file (before staging)
git checkout -- filename.py

# Unstage a file (keep changes)
git reset HEAD filename.py

# Revert to a previous commit
git revert <commit-hash>
```

### Creating Branches (for experiments)

```powershell
# Create a new branch
git branch feature-name

# Switch to the branch
git checkout feature-name

# Or create and switch in one command
git checkout -b feature-name

# List all branches
git branch

# Merge branch back to main
git checkout main
git merge feature-name
```

## Backup to GitHub (Optional)

1. Create a repository on GitHub
2. Link your local repository:
   ```powershell
   git remote add origin https://github.com/yourusername/arbitrage.git
   git branch -M main
   git push -u origin main
   ```

3. Push future changes:
   ```powershell
   git push
   ```

## Important Notes

- The `.gitignore` file prevents sensitive files (like `.env`) from being committed
- Always commit regularly to protect your work
- Use descriptive commit messages
- Consider using branches for major changes or experiments

## Quick Reference

| Command | Purpose |
|---------|---------|
| `git status` | Check current state |
| `git add .` | Stage all changes |
| `git commit -m "message"` | Save changes |
| `git log` | View history |
| `git diff` | See unstaged changes |
| `git branch` | List branches |
| `git checkout -b name` | Create new branch |

## Recovery from Corruption

If files get corrupted, you can restore from any previous commit:

```powershell
# View file at specific commit
git show <commit-hash>:filename.py

# Restore file from specific commit
git checkout <commit-hash> -- filename.py

# Restore entire project to specific commit
git checkout <commit-hash>
```
