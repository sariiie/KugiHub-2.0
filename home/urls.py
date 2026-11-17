from django.urls import path
from . import views

app_name = 'home'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('skills/', views.skills_view, name='skills'),
    path('skills/<int:skill_id>/remove/', views.remove_skill_view, name='remove_skill'),
    path('applications/', views.my_applications_view, name='my_applications'),
    path('applications/<int:application_id>/withdraw/', views.withdraw_view, name='withdraw'),
    path('jobs/<int:job_id>/apply/', views.apply_view, name='apply'),
    path('employer/', views.employer_home_view, name='employer'),
    path('employer/post/', views.post_job_view, name='post_job'),
    path('employer/listings/', views.employer_listings_view, name='listings'),
    path('employer/jobs/<int:job_id>/', views.job_detail_view, name='job_detail'),
    path('employer/jobs/<int:job_id>/edit/', views.job_edit_view, name='job_edit'),
    path('employer/jobs/<int:job_id>/cancel/', views.job_cancel_view, name='job_cancel'),
    path('employer/jobs/<int:job_id>/advance/', views.job_advance_view, name='job_advance'),
    path('employer/applications/<int:application_id>/<slug:decision>/', views.application_decide_view, name='application_decide'),
]
