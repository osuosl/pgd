
   #--------------------------------------------------------------------------------------------------------------------
   # File: CleanDB.php
   # Purpose: Classes and defs associated with plotting data. 
   # Author: Mike Marr
   # Date: 9/28/05
   # Use: Use ConfDistPlot to create a plot, other classes are used by ConfDistPlot
   #-------------------------------------------------------------------------------------------------------------------

import math

import cairo
from django.db.models import Count, Avg, StdDev

from pgd_constants import *
from pgd_core.models import *
from pgd_search.models import *
from pgd_search.statistics.aggregates import DirectionalAvg, DirectionalStdDev
from svg import *

ANGLES = ('ome', 'phi', 'psi', 'chi', 'zeta')
NON_FIELDS = ('Observations', 'all')

"""
COLOR_RANGES - an RGB color setting for determining the range of colors in a plot
Made up of the MAX values for each Red, Green, Blue.  Plus an adjustment for each
RGB value.  A scale will be applied to each number equally then the adjustment added
This causes a range with all colors at the same proportion.  The adjustment causes
a grouping of colors closer to the max value.
"""
COLOR_RANGES = { 
    'green':(
        (255.0,180.0,200.0),
        (0,75,0)
     ),
    'blue':(
        (180.0,200.0,180.0),
        (0,0,75)
     ),
    'red':(
        (130.0, 200.0, 180.0),
        (115,0,0)
    ),
    'black':(
        (180.0,180.0,180.0),
        (75,75,75)
     )
}

LABEL_REPLACEMENTS = {
            "L1":u'C\u207B\u00B9N',
            "L2":u'NC\u1D45',
            "L3":u'C\u1D45C\u1D5D',
            "L4":u'C\u1D45C',
            "L5":u'CO',
            "a1":u'C\u207B\u00B9NC\u1D5D',
            "a2":u'NC\u1D45C\u1D5D',
            "a3":u'NC\u1D45C',
            "a4":u'C\u1D5DC\u1D45C',
            "a5":u'C\u1D45CO',
            "a6":u'C\u1D45CN\u207A\u00B9',
            "a7":u'OCN\u207A\u00B9',
            "ome":u'\u03C9',
            "chi":u'\u03C7',
            "phi":u'\u03D5',
            "psi":u'\u03A8',
            'zeta':u'\u03B6',
            'h_bond_energy':'H Bond'
            }


# getCircularStats: returns (average, standard deviation) of a list of values
#   values: a list of the values to be examined
#   size:   the size of the list (in case it has been counted elsewhere)
def getCircularStats(values,size):

    # Store locals for speed
    lsin = math.sin
    lcos = math.cos
    lradians = math.radians
    lpow = math.pow

    # Circular Average - use some fancy trig that takes circular values
    #   into account.  This requires all values to be converted to radians.
    values = filter(lambda x:x!=None, values)
    size = len(values)

    if size == 1:
        return values[0],0

    radAngles = [lradians(val) for val in values]
    radAvg = math.atan2(
        sum([lsin(radAngle) for radAngle in radAngles])/size,
        sum([lcos(radAngle) for radAngle in radAngles])/size,
    )

    # Standard Deviation - shift the range of deviations +180 by applying
    #   %(2*pi) to all angles.  This creates a range of deviations -180-540.
    #   Values greater than 180 are then shifted back by substracting from
    #   360, resulting in deviations -180-180.  From there the Stdev formula
    #   is the same.
    msum = 0
    lpi = math.pi
    lpi_2 = lpi*2
    for radAngle in radAngles:
        straight = radAngle%lpi_2 - radAvg
        msum += lpow(straight if straight < lpi else lpi_2 - straight, 2)

    return math.degrees(radAvg),math.degrees(math.sqrt(msum/(size-1)))

# getLinearStats: returns (average, standard deviation) of a list of values
#   values: a list of the values to be examined
#   size:   the size of the list (in case it has been counted elsewhere)
def getLinearStats(values,size):

    # Average
    avg = sum(values)/size

    # Standard Deviation
    return avg,math.sqrt(
        sum([
            pow(value - avg, 2)
            for value in values
        ])/(size-1)
    )


class ConfDistPlot():
    """ 
     Class that plots conformation distribution plots
     Construction: X, Y image dimensions
                                 X, Y offsets from top left corner
                                 Query to used to populate plot
    """ 

    
    def __init__(self, xSize, ySize, xMin, xMax, yMin, yMax,
                 xbin, ybin, xText, yText, ref, sigmaVal, residue_attribute,
                 residue_xproperty, residue_yproperty, querySet,
                 color='green',
                 background_color='#ffffff',
                 graph_color='#222222',
                 text_color='#000000',
                 hash_color='#666666'
                 ):
        """
         Constructor
         Size:     size of plot
         Padding:  space to either side of the plot
         0ffset:   offset from top right corner of image for plot to begining
         Min, Max: min and max field values of plot
         bin:      field value size of a bin
         Text:     field name to plot on each axis
         ref:      field name of interest (if 'all', observation count is plotted)
         residue:  index of the residue of interest (-n...-1,0,1...n)
         querySet: Django queryset
         
         color:    Hue to use for bin colorations
         background_color: color used for background of entire image
         graph_color: color used for background of plotted area
         text_color: color used for axis labels, hash labels, and title
         hash_color: color used for axis and hashes
        """
    
        # Convert unicode to strings
        xText,yText,ref = str(xText),str(yText),str(ref)
    
        # save properties
        self.querySet = querySet
        self.ref = ref
        self.xText = xText
        self.yText = yText
        self.x = xMin
        self.x1 = xMax
        self.y = yMin
        self.y1 = yMax
        self.sigmaVal = sigmaVal
        
        self.width = xSize
        self.height = ySize
        self.color = color
        self.background_color = background_color
        self.graph_color = graph_color
        self.text_color = text_color
        self.hash_color = hash_color    

        # Width/height in field units of graph bins
        self.xbin = xbin
        self.ybin = ybin

        # Difference between the possible min and max axes values
        xLimit = xMax - xMin
        yLimit = yMax - yMin
        #   Adjustments for circular quantities
        if xText in ANGLES:
            xModder = int(360/xbin)
            if xMax < xMin:
                xLimit = xLimit%360
        if yText in ANGLES:
            yModder = int(360/ybin)
            if yMax < yMin:
                yLimit = yLimit%360

        # Index of the residue of interest in the segment
        self.residue_attribute = residue_attribute
        self.residue_xproperty = residue_xproperty
        self.residue_yproperty = residue_yproperty



    def query_bins(self, svg, xOffset, yOffset, height, width):
        """
        Runs the query to calculate the bins and their relevent data
        """
        # local vars
        x = self.x
        x1 = self.x1
        y = self.y
        y1 = self.y1
        xbin = self.xbin
        ybin = self.ybin

        # Dictionary of bins, keyed by a tuple of x-y coordinates in field units
        #   i.e. (<x value>, <y value>)
        self.bins = {}

        # Variable to store number of values in the bin with the most values
        self.maxObs = 0

        # get field prefix for this residue
        self.resString, self.refString = self.create_res_string(self.residue_attribute, self.ref)
        self.resXString, self.xTextString = self.create_res_string(self.residue_xproperty, self.xText)
        self.resYString, self.yTextString = self.create_res_string(self.residue_yproperty, self.yText)

        # Exclude values outside the plotted values
        querySet = self.querySet.filter(
            (Q(**{
                '%s__gte'%self.xTextString: x,
                '%s__lt'%self.xTextString: x1,
            }) if (x <= x1) else ( # Altered logic for circular values
                Q(**{'%s__gte'%self.xTextString: x}) |
                Q(**{'%s__lt'%self.xTextString: x1})
            )) & (Q(**{
                '%s__gte'%self.yTextString: y,
                '%s__lt'%self.yTextString: y1,
            }) if (y <= y1) else ( # altered logic for circular values
                Q(**{'%s__gte'%self.yTextString: y}) |
                Q(**{'%s__lt'%self.yTextString: y1})
            ))
        )

        # Total # of observations
        self.numObs = querySet.count()

        # index set creation
        self.index_set = set([self.resString,self.resXString,self.resYString])
        
        # Pick fields for retrieving values
        if self.ref == "Observations":
            self.fields = [(self.xText,self.xTextString), (self.yText,self.yTextString)]
            self.stats_fields = []
        elif self.ref == "all":
            self.fields = [(field,i%(str(field))) for field in ([field for field,none in PLOT_PROPERTY_CHOICES]) for i in self.index_set]
            self.stats_fields = self.fields
        else:
            self.fields = [(self.xText,self.xTextString), (self.yText,self.yTextString), (self.ref,self.refString)]
            self.stats_fields = [(self.ref,self.refString)]

        # create set of annotations to include in the query
        annotations = {'count':Count('id')}
        torsion_avgs = {}
        for field in self.fields:
            avg = '%s_avg' % field[1]
            stddev = '%s_stddev' % field[1]
            if field[0] in ANGLES:
                annotations[avg] = DirectionalAvg(field[1])
                torsion_avgs[field[0]] = {}
            else:
                annotations[avg] = Avg(field[1])
                annotations[stddev] = StdDev(field[1])
        annotated_query = querySet.annotate(**annotations)

        # determine aliases used for the table joins.  This is needed because
        # the aliases will be different depending on what fields were queried
        # even if the query is length 10, not all residues will be joined unless
        # each residue has a property in the where clause.
        x_alias = self.determine_alias(annotated_query, self.residue_xproperty)
        y_alias = self.determine_alias(annotated_query, self.residue_yproperty)
        attr_alias = self.determine_alias(annotated_query, self.residue_attribute)
        x_field = '%s.%s' % (x_alias, self.xText)
        y_field = '%s.%s' % (y_alias, self.yText)

        # calculating x,y bin numbers for every row.  This allows us
        # to group on the bin numbers automagically sorting them into bins
        # and applying the aggregate functions on them.
        x_aggregate = 'FLOOR((%s-%s)/%s)' % (x_field, x, xbin)
        y_aggregate = 'FLOOR((%s-%s)/%s)' % (y_field, y, ybin)
        annotated_query = annotated_query.extra(select={'x':x_aggregate, 'y':y_aggregate}).order_by('x','y')

        # add all the names of the aggregates and x,y properties to the list 
        # of fields to display.  This is required for the annotation to be
        # applied with a group_by.
        values = annotations.keys() + ['x','y']
        annotated_query = annotated_query.values(*values)

        # XXX remove the id field from the group_by.  By default django 
        # adds this to the group by clause.  This would prevent grouping
        # because the id is a unique field.  There is no official API for 
        # modifying group by and this is a big hack, but its a very simple
        # way of making this work
        annotated_query.query.group_by = []

        # calculate bin count and sizes.
        xBinCount = math.floor(x1/xbin) - math.floor(x/xbin)
        yBinCount = math.floor(y1/ybin) - math.floor(y/ybin)
        binWidth = math.floor((width-xBinCount+1)/xBinCount)
        binHeight = math.floor((height-yBinCount+1)/yBinCount)

        for entry in annotated_query:
            x = int(entry['x'])
            y = int(entry['y'])
            key = (x,y)

            #if xText in ANGLES: xDex = xDex%xModder
            #if yText in ANGLES: yDex = yDex%yModder

            # add  entry to the bins dict
            bin = {
                'count' : entry['count'],
                'obs'         : [entry],
                'pixCoords'   : {
                    # The pixel coordinates of the x and y values
                    'x' : x*(binWidth+1)+xOffset+1,
                    'y' : y*(binHeight+1)+yOffset+1,
                    'width'  : binWidth,
                    'height' : binHeight,
                }
            }

            # add all statistics
            for k, v in entry.items():
                if k in ('x','y','count'):
                    continue
                bin[k] = v 

            if bin['count'] > 1:
                # if this is an angle the stddev must be calculated in separate query
                # using the circular standard deviation method
                #
                # due to null causing errors, each field must be run separate to filter
                # out nulls for just that field
                for field in self.stats_fields:
                    if field[0] in ANGLES:
                        if avg:
                            torsion_avgs[field[0]]["'%s:%s'" % (x,y)] = bin[avg]

            else:
                # no need for calculation, stddev infered from bincount
                for field in self.fields:
                    if field[0] in ANGLES:
                        bin['%s_stddev' % field[1]] = 0

            self.bins[key] = bin

            # Find the bin with the most observations
            if self.maxObs < bin['count']:
                self.maxObs = bin['count']

        # run queries to get stddevs for all torsion angles
        # this is done outside the main loop because all of the averages 
        # must first be collected so that they can be run in a single query
        #
        # This query uses a large case statement to select the average matching
        # the bin the result is grouped into.  This isn't the cleanest way
        # of doing this but it does work
        
        for field in self.stats_fields:
            if field[0] in ANGLES:
                stddev = '%s_stddev' % field[1]
                cases = ' '.join(['WHEN %s THEN %s' % (k,v) if v else '' for k,v in torsion_avgs[field[0]].items()])
                avgs = "CASE CONCAT(FLOOR((%s-%s)/%s),':',FLOOR((%s-%s)/%s)) %s END" % (x_field, x, xbin, y_field, y, ybin, cases)
                annotations = {stddev:DirectionalStdDev(field[1], avg=avgs)}
                bin_where_clause = ['NOT %s.%s IS NULL' % (attr_alias, field[0])]
                stddev_query = querySet \
                                    .extra(select={'x':x_aggregate, 'y':y_aggregate}) \
                                    .extra(where=bin_where_clause) \
                                    .annotate(**annotations) \
                                    .values(*annotations.keys()+['x','y']) \
                                    .order_by('x','y')
                stddev_query.query.group_by = []

                for r in stddev_query:
                    value = r[stddev] if r[stddev] else 0
                    self.bins[(r['x'],r['y'])][stddev] = value


    def create_res_string(self, index, property):
        """
        helper function for creating property references
        """
        if index == 0:
            prefix = ''
        elif index < 0:
            prefix = ''.join(['prev__' for i in range(index, 0)])
        else:
            prefix = ''.join(['next__' for i in range(index)])
        resString = '%s%%s' % prefix
        refString = '%s%s' % (prefix, property)
        
        return resString, refString
    
    
    def determine_alias(self, query, index):
        """
        determines the table alias used for a given residue index.
        
        XXX This takes into account django internal structure as of 12/29/2009
        this may change with future releases.
        
        query.join_map is a dict mapping a tuple of (table1, table2, fk, key)
        mapped to a list of aliases the table is joined on.  multiple aliases
        means the table was joined on itself multiple times.
        
        we must walk the list of joins to find the index number we want.
        
        @returns alias if table is joined, otherwise None
        """
        query = query.query
        if index == 0:
            return 'pgd_core_residue'
        if index > 0:
            k = ('pgd_core_residue','pgd_core_residue','next_id','id')
        else:
            k = ('pgd_core_residue','pgd_core_residue','prev_id','id')
            
        if not query.join_map.has_key(k):
            return None
        try:
            return query.join_map[k][int(math.fabs(index))-1]
        except IndexError:
            return None

        
            
    
    def Plot(self):
        """
        Calculates and renders the plot
        """
        
        #cache local variables
        x1 = self.x1
        y1 = self.y1
        xText = self.xText
        yText = self.yText
        height = self.height
        width = self.width
        bg_color = self.background_color
        hash_color = self.hash_color
        text_color = self.text_color

        svg = SVG()

        #run calculations
        #TODO move down from init

        # draw background
        #size ratio (470 = 1)
        ratio = width/560.0
    
        # offsets setup to give 415px for the graph for a default width of 520
        graph_x = round(width*.17857);
        graph_y = round(height*.11702);
        graph_height = height-2*graph_y;
        graph_width = width-2*graph_x;
        hashsize = 10*ratio
        
        #image background
        svg.rect(0, 0, height+30, width, 0, bg_color, bg_color);
        #graph background
        svg.rect(graph_x, graph_y, graph_height, graph_width, 0, self.graph_color, self.graph_color);
        #border
        svg.rect(graph_x+1, graph_y+1, graph_height, graph_width, 1, text_color);

        #draw data area (bins)
        self.query_bins(svg, graph_x, graph_y, graph_height, graph_width)
        self.render_bins(svg)

        #axis
        if self.x < 0 and self.x1 > 0:
            xZero = (graph_width/(self.x1-self.x)) * abs (self.x)
            svg.line( graph_x+xZero, graph_y, graph_x+xZero, graph_y+graph_height, 1, hash_color);
    
        if self.y < 0 and self.x1 > 0:
            yZero = graph_height+graph_y - (graph_height/(y1-self.y)) * abs (self.y)
            svg.line( graph_x, yZero, graph_x+graph_width, yZero, 1, hash_color);

        #hashes
        for i in range(9):
            hashx = graph_x+(graph_width/8.0)*i
            hashy = graph_y+(graph_height/8.0)*i
            svg.line( hashx, graph_y+graph_height, hashx, graph_y+graph_height+hashsize, 1, hash_color);
            svg.line( graph_x, hashy, graph_x-hashsize, hashy, 1, self.hash_color);
    
        #create a cairo surface to calculate text sizes
        surface = cairo.ImageSurface (cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context (surface)
        ctx.set_font_size (12);
    
        #hash labels
        xstep = ((x1 - self.x)%360 if xText in ANGLES else (x1 - self.x))/ 4
        if not xstep: xstep = 90
        #ystep = (self.y1 - self.y) / 4
        ystep = ((y1 - self.y)%360 if yText in ANGLES else (y1 - self.y))/ 4
        if not ystep: ystep = 90
    
        #get Y coordinate for xaxis hashes, this is the same for all x-labels
        xlabel_y = graph_y+graph_height+hashsize*3+(5*ratio)
        for i in range(5):
            #text value
            xtext = ((self.x + xstep*i + 180)%360 - 180) if self.xText in ANGLES else (self.x + xstep*i)
            #drop decimal if value is an integer
            xtext = '%i' % int(xtext) if not xtext%1 else '%.1f' %  xtext
            #get X coordinate of hash, offsetting for length of text
            xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(xtext)
            xlabel_x = graph_x+(graph_width/4)*i-xbearing-twidth/2+1
            #create label
            svg.text(xlabel_x, xlabel_y, xtext,12*ratio, text_color)
    
            #text value
            #ytext = self.y1 - ystep*i
            ytext = ((self.y + ystep*i + 180)%360 - 180) if self.yText in ANGLES else (self.y + ystep*i)
            #drop decimal if value is an integer
            ytext = '%i' % int(ytext) if not ytext%1 else '%.1f' % ytext
            #get Y coordinate offsetting for height of text
            xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(ytext)
            #ylabel_y = y+((graph_height+8)/4)*i-ybearing-theight/2
            ylabel_y = graph_y+(graph_height/4)*(4-i)+(4*ratio)-ybearing/2-theight/2
            #Get X coordinate offsetting for length of hash and length of text
            ylabel_x = (graph_x-(ratio*15))-xbearing-twidth
            #create label
            svg.text(ylabel_x, ylabel_y, ytext,12*ratio, text_color)

        #title text
        xTitle = LABEL_REPLACEMENTS[xText] if xText in LABEL_REPLACEMENTS else xText
        yTitle = LABEL_REPLACEMENTS[yText] if yText in LABEL_REPLACEMENTS else yText
        title = 'Plot of %s vs. %s' % (xTitle,yTitle)
        xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(title)
        title_x = (width/2) - xbearing - twidth/2
        svg.text(title_x,15*ratio, title, 12*ratio, text_color)
    
        attribute_title = LABEL_REPLACEMENTS[self.ref] if self.ref in LABEL_REPLACEMENTS else self.ref
        title = 'Shading Based Off of %s' % attribute_title
        xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(title)
        title_x = (width/2) - xbearing - twidth/2
        svg.text(title_x,35*ratio, title, 12*ratio, text_color)
    
        #axis labels
        ctx.set_font_size (18*ratio);
        xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(xTitle)
        title_x = (width/2) - xbearing - twidth/2
        svg.text(title_x,graph_y+graph_height+hashsize*5+(15*ratio), xTitle, 18*ratio, text_color)
    
        xbearing, ybearing, twidth, theight, xadvance, yadvance = ctx.text_extents(yTitle)
        title_y = (graph_x-(ratio*35))-xbearing-twidth
        svg.text(title_y,graph_y+(graph_height/2)-ybearing-theight/2, yTitle, 18*ratio, text_color)

        return svg


    def render_bins(self, svg):
        """
        Renders the already calculated bins.
        """
        sig = self.sigmaVal
        # Calculate stats regarding the distribution of averages in cells
        if self.ref not in NON_FIELDS and len(self.bins):
            if self.ref in ANGLES:
                meanPropAvg,stdPropAvg = getCircularStats([bin['%s_avg'%self.refString] for bin in self.bins.values()], len(self.bins))
                stdPropAvgXSigma = 180 if stdPropAvg > 60 else sig*stdPropAvg
            else:
                meanPropAvg,stdPropAvg = getLinearStats([bin['%s_avg'%self.refString] for bin in self.bins.values()], len(self.bins))
                minPropAvg = meanPropAvg - sig*stdPropAvg
                maxPropAvg = meanPropAvg + sig*stdPropAvg

        colors, adjust = COLOR_RANGES[self.color]
        # Color the bins
        for key in self.bins:
            bin = self.bins[key]
            num = bin['count']

            if self.ref in NON_FIELDS:
                scale = math.log(num+1, self.maxObs+1)
                color = map(
                    lambda x: x*scale,
                    colors
                )
            elif self.ref in ANGLES:
                avg = bin['%s_avg'%self.refString]
                if avg and '%s_stddev'%self.refString in bin:
                    straight = avg - meanPropAvg
                    difference = (
                        straight
                    ) if -180 < straight < 180 else (
                        (360 if straight < 0 else -360) + straight
                    )
                else:
                    # no average, mark bin as outlier
                    difference = 9999

                if -difference >= stdPropAvgXSigma or difference >= stdPropAvgXSigma:
                    color = [255,-75,255]
                else:
                    scale = 0.5+((
                            math.log(
                                difference+1,
                                stdPropAvgXSigma+1
                            )
                        ) if difference >= 0 else (
                            -math.log(
                                -difference+1,
                                stdPropAvgXSigma+1
                          )
                       ))/2
                    color = map(
                        lambda x: x*scale,
                        colors
                    )
            else:
                avg = bin['%s_avg'%self.refString]
                if avg <= minPropAvg or avg >= maxPropAvg:
                    color = [255,-75,255]
                else:
                    scale = 0.5+((
                            math.log(
                                avg-meanPropAvg+1,
                                maxPropAvg-meanPropAvg+1
                            )
                        ) if avg > meanPropAvg else (
                            -math.log(
                                meanPropAvg-avg+1,
                                meanPropAvg-minPropAvg+1
                            )
                        ))/2
                    color = map(
                        lambda x: x*scale,
                        colors
                    )

            color[0] += adjust[0]
            color[1] += adjust[1]
            color[2] += adjust[2]

            #convert decimal RGB into HEX rgb
            fill = '#%s' % ''.join('%02x'%round(x) for x in color)

            # add rectangle to list
            if self.ref in NON_FIELDS:
                bin_avg, bin_stddev = 0,0 
            else:
                try:
                    bin_avg = bin['%s_avg'%self.refString]
                    bin_stddev = bin['%s_stddev'%self.refString]
                    if bin_avg == None:
                        continue
                except KeyError:
                    continue

            svg.rect(
                    bin['pixCoords']['x'],
                    bin['pixCoords']['y'],
                    bin['pixCoords']['height'],
                    bin['pixCoords']['width'],
                    0,
                    fill,
                    fill,
                    data = [
                        bin['count'],
                        key,
                        bin_avg,
                        bin_stddev
                    ]
            )


    def PrintDump(self, writer):
        """
        Prints out the query results in a dump file
        
        @param writer - any object that has a write(str) method
        """
        if not self.bins:
            self.query_bins()

        residue = self.residue_attribute
        residueX = self.residue_xproperty
        residueY = self.residue_yproperty

        #fields to include, order in this list is important
        STATS_FIELDS = ('phi','psi','ome','L1','L2','L3','L4','L5','a1','a2','a3','a4','a5','a6','a7','chi','zeta')
        avgString = 'r%i_%s_avg'
        stdString = 'r%i_%s_stddev'

        index_set = set([residue,residueX,residueY])

        STATS_FIELDS_STRINGS = reduce(
            lambda x,y:x+y,
            ((avgString%(i,stat),stdString%(i,stat)) for stat in STATS_FIELDS for i in index_set),
        )

        lower_case_fields = ['a1','a2','a3','a4','a5','a6','a7']
        field_replacements = {
            'L1':u'C(-1)N',
            'L2':u'N-CA',
            'L3':u'CA-CB',
            'L4':u'CA-C',
            'L5':'C-O',
            'a1':u'C(-1)-N-CA',
            'a2':u'N-CA-CB',
            'a3':u'N-CA-C',
            'a4':u'CB-CA-C',
            'a5':u'CA-C-O',
            'a6':u'CA-C-N(+1)',
            'a7':u'O-C-N(+1)',
            'h_bond_energy':'HBond'
        }


        #capitalize parameters where needed
        if self.xText in lower_case_fields:
            xText = self.xText
        else:
            xText = self.xText.capitalize()

        if self.yText in lower_case_fields:
            yText = self.yText
        else:
            yText = self.yText.capitalize()

        #output the dynamic titles
        writer.write('%sStart' % xText)
        writer.write('\t')
        writer.write('%sStop' % xText)
        writer.write('\t')
        writer.write('%sStart' % yText)
        writer.write('\t')
        writer.write('%sStop' % yText)
        writer.write('\t')
        writer.write('Observations')

        residue_replacements = {
            0:u'(i-4)',
            1:u'(i-3)',
            2:u'(i-2)',
            3:u'(i-1)',
            4:u'(i)',
            5:u'(i+1)',
            6:u'(i+2)',
            7:u'(i+3)',
            8:u'(i+4)',
            9:u'(i+5)'
        }

        #output the generic titles
        for title in STATS_FIELDS:
            if title in field_replacements:
                title = field_replacements[title]
            elif not title in lower_case_fields:
                title = title.capitalize()
            writer.write('\t')
            writer.write('%sAvg%s' % (title,residue_replacements[self.residue_attribute]))
            writer.write('\t')
            writer.write('%sDev%s' % (title,residue_replacements[self.residue_attribute]))

        #output the generic titles for x res
        for title in STATS_FIELDS:
            if title in field_replacements:
                title = field_replacements[title]
            elif not title in lower_case_fields:
                title = title.capitalize()
            if len(index_set) > 1:
                writer.write('\t')
                writer.write('%sAvg%s' % (title,residue_replacements[self.residue_xproperty]))
                writer.write('\t')
                writer.write('%sDev%s' % (title,residue_replacements[self.residue_xproperty]))

        #output the generic titles for y res
        for title in STATS_FIELDS:
            if title in field_replacements:
                title = field_replacements[title]
            elif not title in lower_case_fields:
                title = title.capitalize()
            if len(index_set) == 3:
                writer.write('\t')
                writer.write('%sAvg%s' % (title,residue_replacements[self.residue_yproperty]))
                writer.write('\t')
                writer.write('%sDev%s' % (title,residue_replacements[self.residue_yproperty]))

        # Cycle through the binPoints
        xbin = self.xbin
        ybin = self.ybin
        for key in self.bins:
            bin = self.bins[key]
            writer.write('\n')

            # x axis range
            writer.write(key[0]*xbin)
            writer.write('\t')
            writer.write((key[0]+1)*xbin)

            # y-axis range
            writer.write('\t')
            writer.write(key[1]*ybin)
            writer.write('\t')
            writer.write((key[1]+1)*ybin)

            # observations
            writer.write('\t')
            writer.write(bin['count'])

            # Start averages and standard deviations
            for fieldStat in STATS_FIELDS_STRINGS:
                writer.write('\t')
                val = bin[fieldStat] if fieldStat in bin else 0
                writer.write(val if val else 0)


# ******************************************************
# Returns default reference values
# ******************************************************
def RefDefaults():
    return {
                'phi': {
                        'min':-180,
                        'max':180,
                        'stepsize':10},
                'L1': {
                        'stepsize':'',
                        'min':'',
                        'max':'',},
                'L2': {
                        'stepsize':'',
                        'min':'',
                        'max':''},
                'L3': {
                        'stepsize':'',
                        'min':'',
                        'max':''
                        },
                'L4': {
                        'stepsize':'',
                        'min':'',
                        'max':''},
                'L5': {
                        'stepsize':'',
                        'min':'',
                        'max':''},
                'L6': {
                        'stepsize':'',
                        'min':'',
                        'max':''},
                'L7': {
                        'ref': 1.465,
                        'stepsize':'',
                        'min':'',
                        'max':''},
                'a1': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a2': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a3': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a4': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a5': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a6': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'a7': {
                        'min':'',
                        'max':'',
                        'stepsize':''},
                'ome':{
                        'min':-180,
                        'max':180,
                        'stepsize':10},
                'chi':{
                        'min':-180,
                        'max':180,
                        'stepsize':10},
                'zeta':{
                        'min':-180,
                        'max':180,
                        'stepsize':10}
                }

if __name__ == "__main__":
    cdp = ConfDistPlot(400, 400, 100, 100,
                    -180, 180,
                    -180, 180,
                    10, 10,
                    "phi", "psi",
                    '1sny',
                    'Observations')

    svg = cdp.Plot()
    print svg.rects
