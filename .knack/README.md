# .knack/ — workspace agent skills

This directory is managed by the [knack](https://getknack.ai) CLI.

```
skills/   pulled skills (consume here)
drafts/   in-progress skill authoring
```

Common commands:

```
knack pull @author/slug      # add a skill to skills/
knack create my-slug --name "Display Name"
                              # scaffold a draft under drafts/my-slug/
knack publish my-slug        # push drafts/my-slug/ as a new version
```

By default `.gitignore` ignores everything in this folder — skills are
rebuildable from the cloud. Comment out entries to pin specific skills
to the repo.
