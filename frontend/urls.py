from django.urls import path
from .views import *

urlpatterns = [
    path('', dashboard, name='dashboard'),
    path('Add_memnbers/',Add_members,name="Add_members"),
    path("get_plan/",get_plan,name="get_plan_details"),
    path('members/',member_list,name="member_list"),
    path('plan/', plans ,name="plans"),
    path('Add_plan/',Add_plan,name="Add_plan"),
    path('toggle_plan/<int:pk>/',toggle_plan,name="toggle_plan"),
    path("plan/<int:pk>/data/", plan_data, name="plan_data"),
    path("plan/<int:pk>/update/", update_plan, name="update_plan"),
    path("plan/<int:pk>/delete/", delete_plan, name="delete_plan"),
    path('member/<int:pk>/delete/',delete_member,name="delete_member"),
    path("member/<int:pk>/data/",Member_data,name="Member_data"),
    path("member/<int:pk>/update/", update_member, name="update_member"),
    
    # View member in detail
    path("members/<int:pk>/full-details/",member_full_details,name="member_full_details"),
    path('members/<int:pk>/renew/',renew_member_plan,name="renew_member_plan"),
    path("branches/<int:pk>/plans/", branch_plans, name="branch_plans"),
    path("renewals/", renewals_page, name="renewals_page"),

    
    path("paid-members/", paid_members_page, name="paid_members_page"),
    path("unpaid-members/", unpaid_members_page, name="unpaid_members_page"),
    
    
    path("profile/", gym_profile, name="gym_profile"),
    path("profile/branch/create/", create_branch, name="create_branch"),
    path("profile/trainer/create/", create_trainer, name="create_trainer"),
    path("profile/trainer/<int:pk>/assign-branch/", assign_trainer_branch, name="assign_trainer_branch"),
    
    
    path("profile/trainer/<int:pk>/toggle/", toggle_trainer, name="toggle_trainer"),
    path("profile/trainer/<int:pk>/update/", update_trainer, name="update_trainer"),
    path("profile/trainer/<int:pk>/delete/", delete_trainer, name="delete_trainer"),

    path("invoice-settings/", invoice_settings_view, name="invoice_settings"),

    path("dashboard/stats/", dashboard_stats, name="dashboard_stats"),
    
    path("dashboard/charts/", dashboard_charts, name="dashboard_charts"),
    path("pending-payments/", pending_payments_page, name="pending_payments"),

    path("pending-payment/<int:member_id>/data/",pending_payment_data, name="pending_payment_data"),
    path("pending-payment/<int:member_id>/pay/",pending_payment_pay, name="pending_payment_pay"),
    path("discount_report",discount_report, name="discount_report"),
    path("invoices/", invoices_page, name="invoices_page"),
    path("backup/download/", backup.download_full_backup, name="download_full_backup"),
    
    path("enquiries/", enquiry_page, name="enquiry_page"),
    path("enquiries/<int:pk>/update/", enquiry_update, name="enquiry_update"),

    path("users/<int:user_id>/reset-password/", reset_user_password, name="reset_user_password"),
    

    path("owner/reset-password/",owner_reset_password, name="owner_reset_password"),

    # whatsapp:
    path("whatsapp_conf/",whatsapp_conf,name="whatsapp_conf"),
    path("whatsapp-logs/", whatsapp_logs_page, name="whatsapp_logs_page"),
    path("payments/<str:payment_id>/invoice-pdf/", generate_invoice_pdf, name="generate_invoice_pdf"),

    # archived_members
    path("members/archived/", archived_members, name="archived_members"),
    path("members/<int:member_id>/restore/", restore_member, name="restore_member"),
    
    #Bulk_save
    path("members/import/",preview_members_excel, name="preview_members_excel"),
    path("members/import/confirm/",confirm_import_members, name="confirm_import_members"),

    #Admission number
    path("update-admission-settings/", update_admission_settings, name="update_admission_settings"),
]
