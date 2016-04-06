from __future__ import unicode_literals

from django.contrib.gis.db.models import PointField
from django.db import models


class CaseInsensitiveTextField(models.TextField):
    """
    See
    http://stackoverflow.com/a/26192509
    http://www.postgresql.org/docs/8.4/static/citext.html
    """
    def db_type(self, connection):
        return 'citext'


class Country(models.Model):
    name = CaseInsensitiveTextField(max_length=100, unique=True)
    iso_code = CaseInsensitiveTextField(max_length=3, unique=True)

    def __unicode__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'countries'


class Category(models.Model):
    name = CaseInsensitiveTextField(max_length=50, unique=True)
    show_on_home_page = models.BooleanField(default=False)

    def __unicode__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'categories'


class Keyword(models.Model):
    name = CaseInsensitiveTextField(max_length=50, unique=True)
    categories = models.ManyToManyField(Category, through='KeywordCategory')
    show_on_home_page = models.BooleanField(default=False)

    def __unicode__(self):
        return self.name

    def formatted_categories(self):
        categories = [
            category.__unicode__() for category in self.categories.all()
        ]
        return ', '.join(categories)
    formatted_categories.short_description = 'Categories'


class KeywordCategory(models.Model):
    """
    We're manually specifying the intermediate table so that we can set
    ForeignKey attributes (specifically, on_delete)
    """
    keyword = models.ForeignKey(Keyword)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)

    class Meta:
        unique_together = ('keyword', 'category')
        verbose_name_plural = 'keyword categories'


class Organisation(models.Model):
    name = models.CharField(max_length=100)

    about = models.CharField(max_length=500, blank=True)

    address = models.CharField(max_length=500, blank=True)
    telephone = models.CharField(max_length=50, blank=True)
    emergency_telephone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    web = models.URLField(blank=True)

    verified_as = models.CharField(max_length=100, blank=True)

    age_range_min = models.PositiveSmallIntegerField(blank=True, null=True)
    age_range_max = models.PositiveSmallIntegerField(blank=True, null=True)

    # might want separate min & max fields / DateTimeField or DurationField
    opening_hours = models.CharField(max_length=50, blank=True)

    country = models.ForeignKey(Country, on_delete=models.PROTECT)

    location = PointField(srid=4326)

    categories = models.ManyToManyField(Category,
                                        through='OrganisationCategory')

    keywords = models.ManyToManyField(Keyword, through='OrganisationKeyword')

    facility_code = models.CharField(max_length=50, blank=True)

    def __unicode__(self):
        return self.name

    def formatted_categories(self):
        categories = [
            category.__unicode__() for category in self.categories.all()
        ]
        return ', '.join(categories)
    formatted_categories.short_description = 'Categories'

    def formatted_keywords(self):
        keywords = [
            keyword.__unicode__() for keyword in self.keywords.all()
        ]
        return ', '.join(keywords)
    formatted_keywords.short_description = 'Keywords'


class OrganisationCategory(models.Model):
    """
    We're manually specifying the intermediate table so that we can set
    ForeignKey attributes (specifically, on_delete)
    """
    organisation = models.ForeignKey(Organisation)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)

    class Meta:
        unique_together = ('organisation', 'category')
        verbose_name_plural = 'organisation categories'


class OrganisationKeyword(models.Model):
    """
    We're manually specifying the intermediate table so that we can set
    ForeignKey attributes (specifically, on_delete)
    """
    organisation = models.ForeignKey(Organisation)
    keyword = models.ForeignKey(Keyword, on_delete=models.PROTECT)

    class Meta:
        unique_together = ('organisation', 'keyword')
        verbose_name_plural = 'organisation keywords'


class OrganisationIncorrectInformationReport(models.Model):
    organisation = models.ForeignKey(Organisation)

    reported_at = models.DateTimeField(auto_now_add=True)

    contact_details = models.NullBooleanField()
    address = models.NullBooleanField()
    trading_hours = models.NullBooleanField()

    other = models.NullBooleanField()
    other_detail = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name_plural = 'Organisations - Incorrect Information Reports'


class OrganisationRating(models.Model):
    POOR = 'poor'
    AVERAGE = 'average'
    GOOD = 'good'
    RATING_CHOICES = (
        (POOR, 'Poor'),
        (AVERAGE, 'Average'),
        (GOOD, 'Good')
    )

    organisation = models.ForeignKey(Organisation)

    rated_at = models.DateTimeField(auto_now_add=True)

    rating = models.CharField(max_length=10, choices=RATING_CHOICES)

    class Meta:
        verbose_name_plural = 'Organisations - Ratings'
