# Contributing to Documentation

We welcome contributions to improve and expand this documentation! Whether you're fixing typos, clarifying instructions, adding new guides, or updating existing content, your help is appreciated.

## How to Contribute

This documentation is hosted on [GitHub Pages](https://pages.github.com/) and built with [MkDocs](https://www.mkdocs.org/) from Markdown files in the [ld-decode repository](https://github.com/happycube/ld-decode). All documentation source files are located in the `docs/` directory.

If you don't have the time or knowledge to work with GitHub, but you spot an issue and still want to help, please use the GitHub issues located in the [ld-decode repository](https://github.com/happycube/ld-decode) - make sure you clearly link the page in question and state what's wrong.

## Quick Start

### Prerequisites

This project uses **Nix** to provide a reproducible development environment with all necessary dependencies, including MkDocs and its plugins. You have two options:

#### Option 1: Using Nix (Recommended)

If you have Nix installed with flakes enabled:

```bash
# Clone the repository
git clone https://github.com/happycube/ld-decode.git
cd ld-decode

# Enter the Nix development shell (this will install all dependencies)
nix develop

# Start the MkDocs development server
mkdocs serve
```

The documentation will be available at `http://127.0.0.1:8000/`

#### Option 2: Manual Installation

If you don't want to use Nix, install MkDocs and its dependencies manually:

```bash
pip install mkdocs mkdocs-material
```

Then run `mkdocs serve` to start the development server.

## Development Workflow

### 1. Fork and Clone

1. **Fork the repository**: Visit [https://github.com/happycube/ld-decode](https://github.com/happycube/ld-decode) and click the "Fork" button to create your own copy.

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR-USERNAME/ld-decode.git
   cd ld-decode
   ```

### 2. Set Up Development Environment

Enter the Nix development shell (if using Nix):

```bash
nix develop
```

This provides:
- MkDocs static site generator
- Material for MkDocs theme
- All required MkDocs plugins

### 3. Create a Branch

```bash
git checkout -b your-feature-branch
```

Use descriptive branch names like `fix-installation-guide` or `add-vbi-documentation`.

### 4. Make Changes

Edit the Markdown files in the `docs/` directory:

```
docs/
├── index.md                    # Homepage
├── Installation/               # Installation guides
├── Tools/                      # Tool documentation
├── How-to-guides/             # Tutorials and guides
├── Hardware/                   # Hardware documentation
└── ...
```

#### Documentation Guidelines

- **Format**: All documentation is written in Markdown (`.md` files)
- **Links**: Keep `.md` extensions in internal links - MkDocs handles them correctly
- **Navigation**: Add new pages to the `nav` section in `mkdocs.yml`
- **Images**: Place images in the appropriate `assets/` subdirectory
- **Code blocks**: Use fenced code blocks with language identifiers for syntax highlighting

### 5. Preview Your Changes

Use MkDocs to preview your changes locally:

```bash
# Start development server with live reload
mkdocs serve
```

Visit `http://127.0.0.1:8000/` to see your changes. The server automatically reloads when you save files.

#### Common MkDocs Commands

```bash
# Serve documentation with live reload
mkdocs serve

# Build static site (output in site/)
mkdocs build

# Build with strict mode (fails on warnings)
mkdocs build --strict

# Serve on different port
mkdocs serve -a localhost:8080
```

### 6. Test Your Changes

Before submitting, ensure:

- [ ] All links work correctly
- [ ] Images display properly
- [ ] Code blocks render with correct syntax highlighting
- [ ] Navigation structure is logical
- [ ] No build warnings: `mkdocs build --strict`

### 7. Commit and Push

```bash
# Stage your changes
git add docs/

# Commit with descriptive message
git commit -m "Add documentation for ld-analyse audio visualization"

# Push to your fork
git push origin your-feature-branch
```

#### Commit Message Guidelines

- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove, etc.)
- Reference issues when applicable: "Fix #123: Correct installation steps"

### 8. Submit Pull Request

1. Go to your fork on GitHub
2. Click "New Pull Request"
3. Select your branch
4. Provide a clear description of your changes
5. Submit for review

PRs are automatically deployed to GitHub Pages once merged.

## Project Structure

### MkDocs Configuration

The `mkdocs.yml` file controls the site configuration:

```yaml
site_name: ld-decode Documentation
theme:
  name: material
nav:
  - Home: index.md
  - Installation: Installation/Installation.md
  # ... more navigation items
```

Key sections:
- `site_name`: Site title
- `theme`: Theme configuration (Material theme)
- `nav`: Navigation structure (table of contents)
- `markdown_extensions`: Enabled Markdown features
- `plugins`: MkDocs plugins

### Adding New Pages

1. Create a new `.md` file in the appropriate `docs/` subdirectory
2. Write your documentation
3. Add the page to `mkdocs.yml` under `nav`:
   ```yaml
   nav:
     - Tools:
       - ld-analyse: Tools/ld-analyse.md
       - Your New Page: Tools/your-new-page.md  # Add this
   ```

### Using Nix Flakes

This project uses Nix flakes for reproducible builds. The `flake.nix` defines:

- Development shell with MkDocs and dependencies
- Consistent environment across all contributors
- Automatic dependency management

To update dependencies, modify `flake.nix` and run:

```bash
nix flake update
```

## Markdown Formatting

This documentation uses [Markdown](https://www.markdownguide.org/) for formatting. Markdown is a lightweight markup language that's easy to read and write.

### Useful Resources

- [Markdown Guide](https://www.markdownguide.org/) - Comprehensive guide to Markdown syntax
- [GitHub Flavored Markdown](https://github.github.com/gfm/) - GitHub's extended Markdown specification
- [MkDocs Documentation](https://www.mkdocs.org/) - MkDocs static site generator
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) - Theme documentation

## Style Guide

### Markdown Conventions

- Use ATX-style headers (`#`, `##`, `###`)
- Use fenced code blocks with language identifiers
- Use relative links for internal documentation
- Include alt text for images

### Writing Style

- Write in clear, concise language
- Use active voice
- Include examples where helpful
- Break complex topics into sections
- Use numbered lists for sequential steps
- Use bulleted lists for non-sequential items

## Questions or Issues?

If you have questions about contributing or encounter any issues, feel free to:

- Open an issue on the [GitHub repository](https://github.com/happycube/ld-decode/issues)
- Join our community on [Discord or IRC](social-media.md) to discuss documentation improvements

Thank you for helping make this documentation better!
