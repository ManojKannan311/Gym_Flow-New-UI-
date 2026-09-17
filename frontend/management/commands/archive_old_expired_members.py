from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from frontend.models import Member  # change app name if needed
from frontend.models import Gym

class Command(BaseCommand):
    help = "Automatically archive expired members based on each gym's auto-archive settings"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()
        total_archived = 0

        gyms = Gym.objects.filter(Auto_archive_enable=True)

        if not gyms.exists():
            self.stdout.write(self.style.WARNING("No gyms have auto archive enabled."))
            return

        for gym in gyms:
            archive_days = gym.Auto_archive_In or 30
            cutoff_date = today - timedelta(days=archive_days)

            members_qs = Member.objects.filter(
                gym=gym,
                is_deleted=False,
                expiry_date__isnull=False,
                expiry_date__lt=cutoff_date,
            )

            archived_count = members_qs.update(is_deleted=True)
            total_archived += archived_count

            self.stdout.write(
                self.style.SUCCESS(
                    f"{gym.name}: archived {archived_count} member(s) expired more than {archive_days} days."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Total archived members: {total_archived}")
        )
        