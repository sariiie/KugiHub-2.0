from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Job, Skill, WorkerSkill


class JobForm(forms.ModelForm):
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Skills needed',
    )

    class Meta:
        model = Job
        fields = ['title', 'description', 'location', 'fee_amount', 'fee_type', 'start_date', 'skills']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean_fee_amount(self):
        fee = self.cleaned_data.get('fee_amount')
        if fee is not None and fee <= 0:
            raise ValidationError('The fee must be greater than zero.')
        return fee

    def clean_start_date(self):
        start = self.cleaned_data.get('start_date')
        # Only complain when the date was changed, so old listings stay editable.
        if start and 'start_date' in self.changed_data and start < timezone.localdate():
            raise ValidationError('The start date cannot be in the past.')
        return start


class WorkerSkillForm(forms.Form):
    """Add a skill to a worker's profile, or update proficiency on one they already have."""
    skill = forms.ModelChoiceField(
        queryset=Skill.objects.all(), required=False,
        empty_label='Choose a skill', label='Skill',
    )
    new_skill = forms.CharField(
        max_length=50, required=False, label="Can't find it? Add a new skill",
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Tile setting'}),
    )
    category = forms.CharField(
        max_length=50, required=False, label='Category (for a new skill)',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Construction'}),
    )
    proficiency = forms.ChoiceField(
        choices=WorkerSkill.Proficiency.choices, label='Proficiency',
        initial=WorkerSkill.Proficiency.INTERMEDIATE,
    )
    years_experience = forms.IntegerField(min_value=0, max_value=60, required=False, label='Years of experience')

    def clean_new_skill(self):
        return ' '.join(self.cleaned_data.get('new_skill', '').split())

    def clean_category(self):
        return ' '.join(self.cleaned_data.get('category', '').split())

    def clean(self):
        cleaned = super().clean()
        skill, new_skill = cleaned.get('skill'), cleaned.get('new_skill')
        if skill and new_skill:
            self.add_error('new_skill', 'Choose a skill from the list or add a new one, not both.')
        elif not skill and not new_skill and 'new_skill' not in self.errors:
            raise ValidationError('Pick a skill from the list, or type a new one.')
        return cleaned

    def save(self, profile):
        """Returns (skill, created). Re-adding a skill the worker already has updates it."""
        data = self.cleaned_data
        skill = data.get('skill')
        if not skill:
            skill = Skill.objects.filter(skill_name__iexact=data['new_skill']).first()
            if not skill:
                skill = Skill.objects.create(skill_name=data['new_skill'], category=data.get('category') or None)
        values = {'proficiency': data['proficiency'], 'years_experience': data.get('years_experience')}
        existing = WorkerSkill.objects.filter(worker=profile, skill=skill)
        if existing.exists():
            existing.update(**values)
            return skill, False
        WorkerSkill.objects.create(worker=profile, skill=skill, **values)
        return skill, True
