from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (EmployerProfile, Job, JobApplication, JobSkill,
                         WorkerProfile, WorkerSkill)

from .forms import JobForm, WorkerSkillForm


def _role_guard(request, role):
    """Send users to the dashboard that matches their role."""
    if request.user.role != role:
        return redirect('home:employer' if request.user.is_employer else 'home:home')
    return None


def _initial(user):
    return (user.first_name[:1] or user.email[:1]).upper()


@login_required
def home_view(request):
    """Worker dashboard: browse open jobs, apply, see own profile."""
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)

    q = request.GET.get('q', '').strip()
    jobs = (Job.objects.filter(status=Job.Status.OPEN)
            .select_related('employer__employer')
            .prefetch_related('skills'))
    if q:
        jobs = jobs.filter(Q(title__icontains=q) | Q(location__icontains=q)
                           | Q(skills__skill_name__icontains=q)).distinct()

    my_skill_ids = set(profile.skills.values_list('pk', flat=True))
    applied_ids = set(profile.applications.exclude(status=JobApplication.Status.WITHDRAWN)
                      .values_list('job_id', flat=True))
    job_cards = []
    for job in jobs[:20]:
        job_skills = list(job.skills.all())
        job_cards.append({
            'job': job,
            'skills': job_skills,
            'matched': any(s.pk in my_skill_ids for s in job_skills),
            'applied': job.pk in applied_ids,
        })
    job_cards.sort(key=lambda c: not c['matched'])   # matched jobs first (stable sort)

    checks = [profile.headline, profile.bio, profile.years_experience,
              my_skill_ids, request.user.phone, request.user.city]
    completion = round(100 * sum(bool(c) for c in checks) / len(checks))

    return render(request, 'home/home.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'job_cards': job_cards,
        'my_skills': profile.worker_skills.select_related('skill'),
        'completed_jobs': profile.assigned_jobs.filter(status=Job.Status.COMPLETED).count(),
        'trust_percent': int(profile.trust_score / 5 * 100),
        'completion': completion,
        'q': q,
    })


@login_required
@require_POST
def apply_view(request, job_id):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    job = get_object_or_404(Job, pk=job_id, status=Job.Status.OPEN)
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    application, created = JobApplication.objects.get_or_create(job=job, worker=profile)
    if created:
        messages.success(request, f'Application sent for "{job.title}".')
    elif application.status == JobApplication.Status.WITHDRAWN:
        application.status = JobApplication.Status.PENDING
        application.applied_at = timezone.now()
        application.save(update_fields=['status', 'applied_at'])
        messages.success(request, f'Application re-sent for "{job.title}".')
    else:
        messages.info(request, 'You already applied to this job.')
    return redirect('home:home')


@login_required
def employer_home_view(request):
    """Employer dashboard: own listings, application counts, trust score."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)

    listings = (profile.jobs.annotate(app_count=Count('applications'))
                .exclude(status=Job.Status.CANCELLED))
    active = listings.filter(status__in=[Job.Status.OPEN, Job.Status.ASSIGNED, Job.Status.IN_PROGRESS])

    checks = [profile.description, profile.address, request.user.phone,
              request.user.city, profile.company_name]
    completion = round(100 * sum(bool(c) for c in checks) / len(checks))

    return render(request, 'home/employer.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'listings': active[:10],
        'active_count': active.count(),
        'application_total': JobApplication.objects.filter(job__employer=profile).count(),
        'completed_jobs': profile.jobs.filter(status=Job.Status.COMPLETED).count(),
        'trust_percent': int(profile.trust_score / 5 * 100),
        'completion': completion,
    })


@login_required
def post_job_view(request):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    form = JobForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        job = form.save(commit=False)
        job.employer = profile
        job.save()
        for skill in form.cleaned_data['skills']:      # JOB_SKILLS rows
            JobSkill.objects.create(job=job, skill=skill)
        messages.success(request, f'"{job.title}" is now live.')
        return redirect('home:employer')
    return render(request, 'home/post_job.html', {
        'form': form, 'initial': _initial(request.user), 'active_nav': 'post',
    })


# ---------------------------------------------------------------------------
# Worker screens: skills + applications
# ---------------------------------------------------------------------------
@login_required
def skills_view(request):
    """Worker: list own skills, add a new one (or create a brand-new skill), edit, remove."""
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)

    editing = None
    initial = None
    if (edit_id := request.GET.get('edit', '').strip()).isdigit():
        editing = profile.worker_skills.select_related('skill').filter(skill_id=int(edit_id)).first()
        if editing:
            initial = {'skill': editing.skill_id, 'proficiency': editing.proficiency,
                       'years_experience': editing.years_experience}

    form = WorkerSkillForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        skill, created = form.save(profile)
        verb = 'added to your profile' if created else 'updated'
        messages.success(request, f'"{skill.skill_name}" {verb}.')
        return redirect('home:skills')

    return render(request, 'home/skills.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'my_skills': profile.worker_skills.select_related('skill').order_by('skill__skill_name'),
        'form': form,
        'editing': editing,
    })


@login_required
@require_POST
def remove_skill_view(request, skill_id):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    ws = profile.worker_skills.select_related('skill').filter(skill_id=skill_id).first()
    if ws:
        name = ws.skill.skill_name
        WorkerSkill.objects.filter(worker=profile, skill_id=skill_id).delete()
        messages.success(request, f'"{name}" removed from your profile.')
    return redirect('home:skills')


@login_required
def my_applications_view(request):
    """Worker: every job they applied to, with its current status."""
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    applications = (profile.applications
                    .select_related('job__employer__employer')
                    .order_by('-applied_at'))
    return render(request, 'home/my_applications.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'applications': applications,
        'pending_count': applications.filter(status=JobApplication.Status.PENDING).count(),
        'accepted_count': applications.filter(status=JobApplication.Status.ACCEPTED).count(),
    })


@login_required
@require_POST
def withdraw_view(request, application_id):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    application = get_object_or_404(JobApplication, pk=application_id, worker=profile)
    if application.status == JobApplication.Status.PENDING:
        application.status = JobApplication.Status.WITHDRAWN
        application.save(update_fields=['status'])
        messages.success(request, f'Application for "{application.job.title}" withdrawn.')
    else:
        messages.info(request, 'Only pending applications can be withdrawn.')
    return redirect('home:my_applications')


# ---------------------------------------------------------------------------
# Employer screens: listings, job detail + applicants, edit, cancel, progress
# ---------------------------------------------------------------------------
def _employer_job(request, job_id):
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    return profile, get_object_or_404(Job, pk=job_id, employer=profile)


@login_required
def employer_listings_view(request):
    """Employer: all own listings, filterable by status."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)

    current = request.GET.get('status', 'all')
    if current not in Job.Status.values:
        current = 'all'

    jobs = profile.jobs.annotate(
        app_count=Count('applications', distinct=True),
        pending_count=Count('applications', filter=Q(applications__status=JobApplication.Status.PENDING),
                            distinct=True),
    )
    if current != 'all':
        jobs = jobs.filter(status=current)

    counts = dict(profile.jobs.order_by().values_list('status').annotate(n=Count('pk')))
    tabs = [{'key': 'all', 'label': 'All', 'count': sum(counts.values())}]
    tabs += [{'key': value, 'label': label, 'count': counts.get(value, 0)} for value, label in Job.Status.choices]

    return render(request, 'home/listings.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'jobs': jobs,
        'tabs': tabs,
        'current': current,
    })


@login_required
def job_detail_view(request, job_id):
    """Employer: one listing with everyone who applied, and accept / decline controls."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _employer_job(request, job_id)

    skills = list(job.skills.all())
    job_skill_ids = {s.pk for s in skills}
    applications = list(job.applications.select_related('worker__worker'))

    worker_skill_ids = {}
    pairs = WorkerSkill.objects.filter(worker_id__in=[a.worker_id for a in applications]).values_list('worker_id', 'skill_id')
    for worker_id, skill_id in pairs:
        worker_skill_ids.setdefault(worker_id, set()).add(skill_id)

    applicants = [{
        'application': a,
        'worker': a.worker,
        'name': a.worker.worker.get_full_name(),
        'matched': len(worker_skill_ids.get(a.worker_id, set()) & job_skill_ids),
    } for a in applications]
    # pending first, then best skill match, then newest
    applicants.sort(key=lambda a: (a['application'].status != JobApplication.Status.PENDING,
                                   -a['matched'], -a['application'].applied_at.timestamp()))

    return render(request, 'home/job_detail.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'job': job,
        'skills': skills,
        'skill_total': len(skills),
        'applicants': applicants,
        'can_edit': job.status == Job.Status.OPEN,
        'can_cancel': job.status in (Job.Status.OPEN, Job.Status.ASSIGNED),
        'can_decide': job.status == Job.Status.OPEN,
    })


@login_required
def job_edit_view(request, job_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _employer_job(request, job_id)
    if job.status != Job.Status.OPEN:
        messages.info(request, 'Only open jobs can be edited.')
        return redirect('home:job_detail', job_id=job.pk)

    form = JobForm(request.POST or None, instance=job)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.save()
            chosen = set(form.cleaned_data['skills'])
            current = set(job.skills.all())
            JobSkill.objects.filter(job=job, skill__in=current - chosen).delete()
            for skill in chosen - current:
                JobSkill.objects.create(job=job, skill=skill)
        messages.success(request, f'"{job.title}" updated.')
        return redirect('home:job_detail', job_id=job.pk)
    return render(request, 'home/post_job.html', {
        'form': form, 'job': job, 'initial': _initial(request.user), 'active_nav': 'listings',
    })


@login_required
@require_POST
def job_cancel_view(request, job_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _employer_job(request, job_id)
    if job.status in (Job.Status.OPEN, Job.Status.ASSIGNED):
        job.status = Job.Status.CANCELLED
        job.save(update_fields=['status'])
        messages.success(request, f'"{job.title}" was cancelled.')
        return redirect('home:listings')
    messages.error(request, 'This job can no longer be cancelled.')
    return redirect('home:job_detail', job_id=job.pk)


@login_required
@require_POST
def job_advance_view(request, job_id):
    """Assigned -> In progress -> Completed."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _employer_job(request, job_id)
    if job.status == Job.Status.ASSIGNED:
        job.status = Job.Status.IN_PROGRESS
        job.save(update_fields=['status'])
        messages.success(request, f'"{job.title}" is now in progress.')
    elif job.status == Job.Status.IN_PROGRESS:
        job.status = Job.Status.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        messages.success(request, f'"{job.title}" marked as completed.')
    else:
        messages.error(request, 'This job cannot be moved forward from its current status.')
    return redirect('home:job_detail', job_id=job.pk)


@login_required
@require_POST
def application_decide_view(request, application_id, decision):
    """Accept (assigns the worker, declines the other pending applicants) or decline one application."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    if decision not in ('accept', 'reject'):
        raise Http404
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    application = get_object_or_404(
        JobApplication.objects.select_related('job', 'worker__worker'),
        pk=application_id, job__employer=profile,
    )
    job = application.job
    name = application.worker.worker.get_full_name()

    if application.status != JobApplication.Status.PENDING:
        messages.info(request, 'This application has already been handled.')
    elif decision == 'reject':
        application.status = JobApplication.Status.REJECTED
        application.save(update_fields=['status'])
        messages.success(request, f'{name} was declined.')
    elif job.status != Job.Status.OPEN:
        messages.error(request, 'This job is no longer open, so no one else can be accepted.')
    else:
        with transaction.atomic():
            application.status = JobApplication.Status.ACCEPTED
            application.save(update_fields=['status'])
            job.applications.filter(status=JobApplication.Status.PENDING).update(status=JobApplication.Status.REJECTED)
            job.assigned_worker = application.worker
            job.status = Job.Status.ASSIGNED
            job.save(update_fields=['assigned_worker', 'status'])
        messages.success(request, f'{name} is now assigned to "{job.title}". Other pending applicants were declined.')
    return redirect('home:job_detail', job_id=job.pk)
