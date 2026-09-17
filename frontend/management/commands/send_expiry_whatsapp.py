from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from frontend.models import Member
from frontend.utils import (
    send_interakt_template,
    already_sent_today,
    get_next_birthday,
)
from frontend.views import can_use_whatsapp

class Command(BaseCommand):
    help = "Send WhatsApp reminders for expiry and birthdays"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()

        members = Member.objects.filter(
            is_deleted=False,
            gym__interakt_enabled=True,
        ).select_related("gym", "plan", "branch")
        
        for member in members:
            gym = member.gym

            if not can_use_whatsapp(gym):
                continue

        self.stdout.write(f"Today: {today}")
        self.stdout.write(f"Matched members count: {members.count()}")

        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for member in members:
            gym = member.gym
            expiry_reminder_days = gym.expiry_reminder_days_before or 7
            expiring_limit = today + timedelta(days=expiry_reminder_days)

            birthday_reminder_days = gym.birthday_reminder_days_before or 10
            birthday_target_date = today + timedelta(days=birthday_reminder_days)

            self.stdout.write(
                f"\nChecking member: {member.name} | Phone: {member.phone} | "
                f"Plan: {member.plan} | Expiry: {member.expiry_date} | "
                f"DOB: {member.DOB} | Gym: {gym.name}"
            )

            if not member.phone:
                self.stdout.write("-> Skipped: no phone")
                skipped_count += 1
                continue

            birthday_message_sent = False

            # =========================
            # BIRTHDAY CHECKS
            # =========================
            if member.DOB:
                next_birthday = get_next_birthday(member.DOB, today)

                # Exact birthday date
                if next_birthday == today:
                    self.stdout.write("-> Member birthday is TODAY")

                    if not gym.wa_template_birthday_today:
                        self.stdout.write("-> Skipped: wa_template_birthday_today is empty")
                        skipped_count += 1

                    elif already_sent_today(member, "birthday_today"):
                        self.stdout.write("-> Skipped: already sent birthday_today message today")
                        skipped_count += 1

                    else:
                        log = send_interakt_template(
                            gym=gym,
                            member=member,
                            template_name=gym.wa_template_birthday_today,
                            body_values=[
                                member.name,
                                gym.name,
                            ],
                            message_type="birthday_today",
                        )

                        self.stdout.write(f"-> Birthday today send result: {log.status}")

                        if log.status in ["queued", "sent", "delivered", "read"]:
                            sent_count += 1
                        else:
                            failed_count += 1

                        birthday_message_sent = True

                # 10 days before birthday
                elif next_birthday == birthday_target_date:
                    self.stdout.write(f"-> Member birthday is in {birthday_reminder_days} days")

                    if not gym.wa_template_birthday:
                        self.stdout.write("-> Skipped: wa_template_birthday is empty")
                        skipped_count += 1

                    elif already_sent_today(member, "birthday_upcoming"):
                        self.stdout.write("-> Skipped: already sent birthday_upcoming message today")
                        skipped_count += 1

                    else:
                        log = send_interakt_template(
                            gym=gym,
                            member=member,
                            template_name=gym.wa_template_birthday,
                            body_values=[
                                member.name,
                                gym.name,
                                next_birthday.strftime("%d-%m-%Y"),
                            ],
                            message_type="birthday_upcoming",
                        )

                        self.stdout.write(f"-> Birthday upcoming send result: {log.status}")

                        if log.status in ["queued", "sent", "delivered", "read"]:
                            sent_count += 1
                        else:
                            failed_count += 1

                        birthday_message_sent = True

            # =========================
            # EXPIRY CHECKS
            # =========================
            if not member.plan:
                self.stdout.write("-> Skipped: no plan")
                skipped_count += 1
                continue

            expiry_date = member.expiry_date
            if not expiry_date:
                self.stdout.write("-> Skipped: no expiry date")
                skipped_count += 1
                continue

            # EXPIRED
            if expiry_date < today:
                self.stdout.write("-> Member is EXPIRED")

                if not gym.wa_template_expired:
                    self.stdout.write("-> Skipped: wa_template_expired is empty")
                    skipped_count += 1
                    continue

                if already_sent_today(member, "expired"):
                    self.stdout.write("-> Skipped: already sent expired message today")
                    skipped_count += 1
                    continue

                log = send_interakt_template(
                    gym=gym,
                    member=member,
                    template_name=gym.wa_template_expired,
                    body_values=[
                        member.name,
                        gym.name,
                        expiry_date.strftime("%d-%m-%Y"),
                    ],
                    message_type="expired",
                )

                self.stdout.write(f"-> Expired send result: {log.status}")

                if log.status in ["queued", "sent", "delivered", "read"]:
                    sent_count += 1
                else:
                    failed_count += 1

            # EXPIRES TODAY
            elif expiry_date == today:
                self.stdout.write("-> Member expires TODAY")

                if not gym.wa_template_expires_today:
                    self.stdout.write("-> Skipped: wa_template_expires_today is empty")
                    skipped_count += 1
                    continue

                if already_sent_today(member, "expires_today"):
                    self.stdout.write("-> Skipped: already sent expires_today message today")
                    skipped_count += 1
                    continue

                log = send_interakt_template(
                    gym=gym,
                    member=member,
                    template_name=gym.wa_template_expires_today,
                    body_values=[
                        member.name,
                        gym.name,
                        expiry_date.strftime("%d-%m-%Y"),
                    ],
                    message_type="expires_today",
                )

                self.stdout.write(f"-> Expires today send result: {log.status}")

                if log.status in ["queued", "sent", "delivered", "read"]:
                    sent_count += 1
                else:
                    failed_count += 1

            # EXPIRING SOON
            elif today < expiry_date <= expiring_limit:
                self.stdout.write("-> Member is EXPIRING SOON")

                if not gym.wa_template_expiring_soon:
                    self.stdout.write("-> Skipped: wa_template_expiring_soon is empty")
                    skipped_count += 1
                    continue

                if already_sent_today(member, "expiring_soon"):
                    self.stdout.write("-> Skipped: already sent expiring_soon message today")
                    skipped_count += 1
                    continue

                log = send_interakt_template(
                    gym=gym,
                    member=member,
                    template_name=gym.wa_template_expiring_soon,
                    body_values=[
                        member.name,
                        gym.name,
                        expiry_date.strftime("%d-%m-%Y"),
                    ],
                    message_type="expiring_soon",
                )

                self.stdout.write(f"-> Expiring soon send result: {log.status}")

                if log.status in ["queued", "sent", "delivered", "read"]:
                    sent_count += 1
                else:
                    failed_count += 1

            else:
                if not birthday_message_sent:
                    self.stdout.write("-> Skipped: no birthday or expiry action needed")
                    skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nWhatsApp job completed. Sent: {sent_count}, Failed: {failed_count}, Skipped: {skipped_count}"
            )
        )