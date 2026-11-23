#!/usr/bin/env bash
# So a failed pg_dump in the backup pipeline is noticed.
set -o pipefail

KEEP_BACKUPS=14

echo "Setting up..."
mkdir backups -p
mkdir configs -p

echo "Pulling latest version from Git..."
git fetch
git pull

commit=$(git log --pretty=format:'%h' -n 1)
branch=$(git branch --show-current)
time_file=$(date +%Y%m%d%H%M%S)
time_bot=$(date "+%d-%m-%Y %H:%M:%S \(UTC\)")

echo "Deploying $branch > $commit"
echo "Updating configs..."
rm configs/git.env -f
touch configs/git.env
{
  echo "COMMIT=$commit
  BRANCH=$branch
  DEPLOY_TIME=$time_bot"
} >> configs/git.env

database_state=$(docker inspect --format="{{.State.Running}}" aurorahue-db 2>/dev/null)
if [[ $* == "--skip-db" ]];
then
  echo "Skipping backup database"
else
  if [ "$database_state" == "true" ];
  then
    echo "Backing up database..."
    backup_file="backups/backup-$time_file.sql.gz"
    if ! docker exec aurorahue-db sh -c 'exec pg_dump -U "${POSTGRES_USER}" "${POSTGRES_DB}"' | gzip > "$backup_file.tmp"; then
      rm -f -- "$backup_file.tmp"
      echo "Error: database backup failed. Aborting update before touching the running containers." >&2
      exit 1
    fi
    mv -- "$backup_file.tmp" "$backup_file"
    echo "Backup saved to $backup_file"

    # Keep only the newest $KEEP_BACKUPS backups. "|| true" covers the no-matches case,
    # where ls fails and pipefail would otherwise abort the script.
    ls -1t backups/backup-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -- || true
  else
    echo "Database container not running, skipping backup"
  fi
fi

echo "Shutting down bot..."
docker compose down

echo "Rebuilding images and launching..."
docker compose up -d --remove-orphans --build

echo "Done! Bot will connect to Discord shortly."
