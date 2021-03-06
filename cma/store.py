#!/usr/bin/env python
# vim: smartindent tabstop=4 shiftwidth=4 expandtab number colorcolumn=100
#
# This file is part of the Assimilation Project.
#
# Author: Alan Robertson <alanr@unix.sh>
# Copyright (C) 2013 - Assimilation Systems Limited
#
# Free support is available from the Assimilation Project community - http://assimproj.org
# Paid support is available from Assimilation Systems Limited - http://assimilationsystems.com
#
# The Assimilation software is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# The Assimilation software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with the Assimilation Project software.  If not, see http://www.gnu.org/licenses/
#
#
# W0212 -- access to a protected member of a client class (we do this a lot)
# pylint: disable=W0212
'''
Store module - contains a transactional batch implementation of Nigel Small's
Object-Graph-Mapping API (or something a lot like it)
'''
import re, inspect, weakref
from collections import namedtuple
#import traceback
import sys # only for stderr
from datetime import datetime, timedelta
import py2neo
from py2neo import neo4j, GraphError
from assimevent import AssimEvent

# R0902: Too many instance attributes (17/10)
# R0904: Too many public methods (27/20)
# pylint: disable=R0902,R0904
class Store(object):
    '''This 'Store' class is a transaction-oriented implementation of Nigel Small's
    OGM (Object-Graph-Mapping) API - with a few extensions and a few things not implemented.

    Unimplemented APIs
    -----------------
    The following member functions aren't provided:
        is_saved() - replaced by the transaction_pending property

    Some interesting extensions:
    ----------------------------
        -   You can tell the Store constructor things about your Classes and Indexes
                makes handling indexes simpler and less error prone. This affects the
                save() method and makes it usable far more often.
        -   All updates are happen in a batch job - as a single transaction.
        -   You never need to call save once an object was created.  We
            track changes to the attributes.

    New methods:
    -----------
        commit          saves all modifications in a single transaction
        load_in_related load objects we're related to by incoming relationships
        load_cypher_nodes generator which yields a vector of sametype nodes from a cypher query
        load_cypher_node return a single object from a cypher query
        load_cypher_query return iterator with objects for fields
        separate_in     separate objects we're related to by incoming relationships
        node            returns the neo4j.Node object associated with an object
        id              returns the id of the neo4j.Node associated with an object
        is_uniqueindex  returns True if the given index name is known to be unique
        __str__         formats information about this Store
        transaction_pending -- Property: True means a transaction is pending
        stats           a data member containing statistics in a dict
        reset_stats     Reset statistics counters and timers

    The various save functions do nothing immediately.  Updates are delayed until
    the commit member function is called.

    Restrictions:
    -------------
    You can't delete something in the same transaction that you created it.
    This could probably be fixed, but would take some effort, and seems unlikely
    to be useful.

    Objects associated with Nodes must be subclasses of object

    Caveats, Warnings and so on...
    ------------------------------
    You can delete the same the same relationship or node multiple times in a transaction.

    Attributes beginning with _ are not replicated as Node properties.

    There are various times when a constructor is called to create an object from a
    node.  Those 'constructors' can be factory functions that construct the right kind
    of object for the type of node involved.

    Such constructors are called with the arguments which correspond to the Node
    properties - but only those which they will legally take (according to python
    introspection).  It is assumed that argument names correspond to attribute
    (Node property) names.

    Any remaining properties not created by the constructor are assigned to the object
    as attributes.  This is likely not what Nigel did, but it seems sensible.

    Probably should have created some new exception type for a few of our cases.
    I'm not compatible with Nigel in terms of exceptions raised. We mostly
    raise ValueError()...

    In particular, it is possible for data in the database to be incompatible with
    object constructors which would be a bad thing worth recognizing -- but I don't
    do anything special for this case at the moment.
    '''
    LUCENE_RE =  re.compile(r'([\-+&\|!\(\)\{\}[\]^"~\*?:\\])')
    LUCENE_RE =  re.compile(r'([:[\]])')

    debug = False
    log = None

    def __init__(self, db, uniqueindexmap=None, classkeymap=None, readonly=False):
        '''
        Constructor for Transactional Write (Batch) Store objects
        ---------
        Parameters:
        db             - Database to associate with this object
        uniqueindexmap - Dict of indexes, True means its a unique index, False == nonunique
        classkeymap    - Map of classes to index attributes - indexed by Class or Class name
                         Values are another Dict with these values:
                         'index':   name of index
                         'key':     constant key value
                         'kattr':   object attribute for key
                         'value':   constant key 'value'
                         'vattr':   object attribute for key 'value'
        '''
        self.db = db
        self.readonly = readonly
        self.stats = {}
        self.reset_stats()
        self.clients = {}
        self.newrels = []
        self.deletions = []
        self.classes = {}
        self.weaknoderefs = {}
        if classkeymap is None:
            classkeymap = {}
        if uniqueindexmap is None:
            uniqueindexmap = {}
            for classkey in classkeymap.keys():
                uniqueindexmap[classkey] = True
        self.uniqueindexmap = uniqueindexmap
        self.batch = None
        self.batchindex = None
        if len(classkeymap) > 0 and not isinstance(classkeymap.keys()[0], str):
            # Then the map should be indexed by the classes themselves
            newmap = {}
            for cls in classkeymap.keys():
                newmap[cls.__name__] = classkeymap[cls]
            classkeymap = newmap
        self.classkeymap = classkeymap
        self.create_node_count = 0
        self.relate_node_count = 0
        self.index_entry_count = 0
        self.node_update_count = 0
        self.node_deletion_count = 0
        self.node_separate_count = 0


    def __str__(self):
        'Render our Store object as a string for debugging'
        ret = '{\n\tdb: %s'                     %       self.db
        ret += ',\n\tclasses: %s'               %       self.classes
        if False and self.uniqueindexmap:
            ret += ',\n\tuniqueindexmap: %s'    %       self.uniqueindexmap
        if False and self.uniqueindexmap:
            ret += ',\n\tclasskeymap: %s'       %       self.classkeymap
        ret += '\n\tbatchindex: %s'             %       self.batchindex
        for attr in ('clients', 'newrels', 'deletions'):
            avalue = getattr(self, attr)
            acomma = '['
            s = "\n"
            for each in avalue:
                s += ('%s%s' % (acomma, each))
                acomma = ', '
            ret += ",\n\t%10s: %s"  % (attr, s)
        ret += '\n%s\n'                         %   self.fmt_dirty_attrs()
        ret += '\n\tweaknoderefs: %s'           %   self.weaknoderefs

        ret += '\n\tstats: %s'                  %   self.stats
        ret += '\n\tbatch: %s'                  %   self.batch
        ret += '\n}'
        return ret

    @staticmethod
    def lucene_escape(query):
        'Returns a string with the lucene special characters escaped'
        return Store.LUCENE_RE.sub(r'\\\1', query)

    @staticmethod
    def id(subj):
        'Returns the id of the neo4j.Node associated with the given object'
        if subj.__store_node.bound:
            return subj.__store_node._id
        return None

    @staticmethod
    def has_node(subj):
        'Returns True if this object has an associated Neo4j Node object'
        return hasattr(subj, '_Store__store_node')

    @staticmethod
    def getstore(subj):
        'Returns the Store associated with this object'
        return subj.__store if hasattr(subj, '_Store__store') else None

    @staticmethod
    def is_abstract(subj):
        'Returns True if the underlying database node is Abstract'
        if not hasattr(subj, '_Store__store_node'):
            return True
        return not subj.__store_node.bound

    @staticmethod
    def bound(subj):
        'Returns True if the underlying database node is bound (i.e., not abstract)'
        return subj.__store_node.bound

    def is_uniqueindex(self, index_name):
        'Return True if this index is known to be a unique index'
        if self.uniqueindexmap is not None and index_name in self.uniqueindexmap:
            return self.uniqueindexmap[index_name]
        return False

    # For debugging...
    def dump_clients(self):
        'Dump out all our client objects and their supported attribute values and states'
        for client in self.clients:
            print >> sys.stderr, ('Client %s:' % client)
            for attr in Store._safe_attr_names(client):
                if attr in client.__store_dirty_attrs.keys():
                    print >> sys.stderr, ('%10s: Dirty - %s' % (attr, client.__dict__[attr]))
                else:
                    print >> sys.stderr, ('%10s: Clean - %s' % (attr, client.__dict__[attr]))

    def fmt_dirty_attrs(self):
        'Format dirty our client objects and their modified attribute values and states'
        result='"Dirty Attrs": {'
        for client in self.clients:
            namedyet = False
            for attr in Store._safe_attr_names(client):
                if not hasattr(client, '__store_dirty_attrs'):
                    continue
                if attr in client.__store_dirty_attrs.keys():
                    if not namedyet:
                        result += ('Client %s:%s: {' % (client, Store.id(client)))
                        namedyet = True
                    result += ('%10s: %s,' % (attr, client.__dict__[attr]))
            if namedyet:
                result += '}\n'
        result += '}'
        return result

    def save_indexed(self, index_name, key, value, *subj):
        'Save the given (new) object as an indexed node'
        if self.readonly:
            raise RuntimeError('Attempt to save an object to a read-only store')
        if not isinstance(subj, tuple) and not isinstance(subj, list):
            subj = (subj,)
        for obj in subj:
            self._register(obj, neo4j.Node(**Store.safe_attrs(obj))
            ,   index=index_name, key=key, value=value, unique=False)

    def save_unique(self, index_name, key, value, subj):
        'Save the given new object as a uniquely indexed node'
        self.save_indexed(index_name, key, value, subj)
        # Override save_indexed's judgment that it's not unique...
        subj.__store_index_unique = True

    def save(self, subj, node=None):
        '''Save an object:
            - into a new node
            - into an existing node

            It will be indexed if its class is a known indexed class
                not indexed if its class is not a known indexed class

            If the index is known to be a unique index, then it will
            be saved unique - otherwise it won't be unique
        '''
        if self.readonly:
            raise RuntimeError('Attempt to save an object to a read-only store')
        if node is not None:
            if subj in self.clients:
                raise ValueError('Cannot save existing node into a new node')
            self._register(subj, node=node)
            return

        # Figure out all the indexed stuff...
        cls = subj.__class__
        if cls.__name__ not in self.classkeymap:
            # Not an indexed object...
            if subj not in self.clients:
                self._register(subj, neo4j.Node(**Store.safe_attrs(subj)))
            return subj
        (index, key, value) = self._get_idx_key_value(cls, subj.__dict__)

        # Now save it...
        if self.is_uniqueindex(index):
            self.save_unique(index, key, value, subj)
        else:
            self.save_indexed(index, key, value, subj)
        return subj

    def delete(self, subj):
        'Delete the saved object and all its relationships from the database'
        if not hasattr(subj, '_Store__store_node'):
            raise ValueError('Object not associated with the Store system')
        if self.readonly:
            raise RuntimeError('Attempt to delete an object from a read-only store')
        node = subj.__store_node
        if not node.bound:
            raise ValueError('Node cannot be abstract')
        self.separate(subj)
        self.separate_in(subj)
        self.deletions.append(subj)

    def refresh(self, subj):
        'Refresh the information in the given object from the database'
        node = self.db.node(subj.__store_node._id)
        return self._construct_obj_from_node(node, subj.__class__)


    def load_indexed(self, index_name, key, value, cls):
        '''
        Return the specified set of 'cls' objects from the given index
        ---------
        Parameters:
        index_name - name of index to retrieve objects from
        key        - key value of nodes to be retrieved
        value      - 'value' of nodes to be retrieved
        cls        - a class to construct -- or a function to call
                     which constructs the desired object
        '''

        idx = self.db.legacy.get_index(neo4j.Node, index_name)
        nodes = idx.get(key, value)
        #print ('idx["%s",%s].get("%s", "%s") => %s' % (index_name, idx, key, value, nodes))
        ret = []
        for node in nodes:
            ret.append(self._construct_obj_from_node(node, cls))
        #print ('load_indexed: returning %s' % ret[0].__dict__)
        return ret

    def load(self, cls, **clsargs):
        '''Load a pre-existing object from its constructor arguments.
        '''
        if cls.__name__ not in self.classkeymap:
            print >> sys.stderr, (self.classkeymap)
            raise ValueError("Class [%s] does not have a known index [%s]"
            %   (cls.__name__, self.classkeymap))
        try:
            (index_name, idxkey, idxvalue) = self._get_idx_key_value(cls, clsargs, subj=clsargs)
        except KeyError:
            # On rare occasions, constructors create some default "unique" values
            # which don't appear as arguments, then the call above fails with KeyError.
            # The rest of the time, just using subj=clsargs is cheaper...
            # There are no cases where it produces different results.
            # If we're called by load_or_save() it will call the constructor again,
            # so it seems good to avoid that.
            subj = self.save(self.callconstructor(cls, clsargs))
            (index_name, idxkey, idxvalue) = self._get_idx_key_value(cls, clsargs, subj=subj)
        if not self.is_uniqueindex(index_name):
            raise ValueError("Class [%s] is not a unique indexed class" % cls)

        # See if we can find this node in memory somewhere...
        ret = self._localsearch(cls, idxkey, idxvalue)
        if ret is not None:
            return ret

        try:
            node = self.db.legacy.get_indexed_node(index_name, idxkey, idxvalue)
        except GraphError:
            return None
        return self._construct_obj_from_node(node, cls, clsargs) if node is not None else None

    def load_or_create(self, cls, **clsargs):
        '''Analogous to 'save' - for loading an object or creating it if it
        doesn't exist
        '''
        obj = self.load(cls, **clsargs)
        if obj is not None:
            return obj
        return self.save(self.callconstructor(cls, clsargs))


    def relate(self, subj, rel_type, obj, properties=None):
        '''Define a 'rel_type' relationship subj-[:rel_type]->obj'''
        assert not isinstance(obj, str)
        if self.readonly:
            raise RuntimeError('Attempt to relate objects in a read-only store')
        self.newrels.append({'from':subj, 'to':obj, 'type':rel_type, 'props':properties})
        if Store.debug:
            print >> sys.stderr, 'NEW RELATIONSHIP FROM %s to %s' % (subj, obj)
            if not Store.is_abstract(subj):
                print >> sys.stderr, 'FROM id is %s' % Store.id(subj)
            if not Store.is_abstract(obj):
                print >> sys.stderr, 'TO id is %s' % Store.id(obj)

    def relate_new(self, subj, rel_type, obj, properties=None):
        '''Define a 'rel_type' relationship subj-[:rel_type]->obj'''
        subjnode = subj.__store_node
        objnode  = obj.__store_node

        # Check for relationships created in this transaction...
        for rel in self.newrels:
            if rel['from'] is subj and rel['to'] is obj and rel['type'] == rel_type:
                return
        # Check for pre-existing relationships
        if objnode.bound and subjnode.bound:
            rels = [rel for rel in subjnode.match_outgoing(rel_type, objnode)]
            if len(rels) > 0:
                return
        self.relate(subj, rel_type, obj, properties)

    def separate(self, subj, rel_type=None, obj=None):
        'Separate nodes related by the specified relationship type'
        fromnode = subj.__store_node
        if not fromnode.bound:
            raise ValueError('Subj Node cannot be abstract')
        if obj is not None:
            obj = obj.__store_node
            if not obj.bound:
                raise ValueError('Obj Node cannot be abstract')

        # No errors - give it a shot!
        rels = subj.__store_node.match_outgoing(rel_type, obj)
        for rel in rels:
            if Store.debug:
                print ('DELETING RELATIONSHIP %s of type %s: %s' % (rel._id, rel_type, rel))
            if obj is not None:
                assert rel.end_node._id == obj._id
            self.deletions.append(rel)

    def separate_in(self, subj, rel_type=None, obj=None):
        'Separate nodes related by the specified relationship type'
        fromnode = subj.__store_node
        if not fromnode.bound:
            raise ValueError('Node cannot be abstract')
        if obj is not None:
            obj = obj.__store_node
            if not obj.bound:
                raise ValueError('Node cannot be abstract')

        # No errors - give it a shot!
        rels = subj.__store_node.match_incoming(rel_type)
        for rel in rels:
            self.deletions.append(rel)

    def load_related(self, subj, rel_type, cls):
        'Load all outgoing-related nodes with the specified relationship type'
        # It would be really nice to be able to filter on relationship properties
        # All it would take would be to write a little Cypher query
        # Of course, that still leaves the recently-created case unhandled...

        if Store.is_abstract(subj):
            # @TODO Should search recently created relationships...
            #raise ValueError('Node to load related to cannot be abstract')
            return
        rels = subj.__store_node.match_outgoing(rel_type)
        for rel in rels:
            yield self._construct_obj_from_node(rel.end_node, cls)

    def load_in_related(self, subj, rel_type, cls):
        'Load all incoming-related nodes with the specified relationship type'
        if not subj.__store_node.bound:
        # All it would take would be to write a little Cypher query
        # Of course, that still leaves the recently-created case unhandled...
            # @TODO Should search recently created relationships...
            raise ValueError('Node to load related from cannot be abstract')
        rels = subj.__store_node.match_incoming(rel_type)
        for rel in rels:
            yield (self._construct_obj_from_node(rel.start_node, cls))

    def load_cypher_nodes(self, querystr, cls, params=None, maxcount=None, debug=False):
        '''Execute the given query that yields a single column of nodes
        all of the same Class (cls) and yield each of those Objects in turn
        through an iterator (generator)'''
        count = 0
        if params is None:
            params = {}
        if debug:
            print >> sys.stderr, 'Starting query %s(%s)' % (querystr, params)
        for row in self.db.cypher.stream(querystr, **params):
            if debug:
                print >> sys.stderr, 'Received Row from stream: %s' % (row)
            for key in row.__producer__.columns:
                if debug:
                    print >> sys.stderr, 'looking for column %s' % (key)
                node = getattr(row, key)
                if node is None:
                    if debug:
                        print >> sys.stderr, 'getattr(%s) failed' % key
                    continue
                yval = self.constructobj(cls, node)
                if debug:
                    print >> sys.stderr, 'yielding row %d (%s)' % (count, yval)
                yield yval
            count += 1
            if maxcount is not None and count >= maxcount:
                if debug:
                    print >> sys.stderr, 'quitting on maxcount (%d)' % count
                break
        if debug:
            print >> sys.stderr, 'quitting on end of query output (%d)' % count
        return

    def load_cypher_node(self, query, cls, params=None):
        'Load a single node as a result of a Cypher query'
        if params is None:
            params = {}
        for node in self.load_cypher_nodes(query, cls, params, maxcount=1):
            return node
        return None

    def load_cypher_query(self, querystr, clsfact, params=None, maxcount=None):
        '''Iterator returning results from a query translated into classes, and so on
        Each iteration returns a namedtuple with node fields as classes, etc.
        Note that 'clsfact' must be a class "factory" capable of translating any
        type of node encountered into the corresponding objects.
        Return result is a generator.
        '''
        count = 0
        if params is None:
            params = {}
        rowfields = None
        rowclass = None
        for row in self.db.cypher.stream(querystr, **params):
            if rowfields is None:
                rowfields = row.__producer__.columns
                rowclass = namedtuple('FilteredRecord', rowfields)
            yieldval = []
            for attr in rowfields:
                yieldval.append(self._yielded_value(getattr(row, attr), clsfact))
            count += 1
            if maxcount is not None and count > maxcount:
                return
            yield rowclass._make(yieldval)

    def _yielded_value(self, value, clsfact):
        'Return the value for us to yield - supporting collection objects'
        if isinstance(value, neo4j.Node):
            obj = self.constructobj(clsfact, value)
            return obj
        elif isinstance(value, neo4j.Relationship):
            from graphnodes import NeoRelationship
            return NeoRelationship(value)
        elif isinstance(value, neo4j.Path):
            return '''Sorry, Path values aren't yet supported'''
        elif isinstance(value, (list, tuple)):
            ret = []
            for elem in value:
                ret.append(self._yielded_value(elem, clsfact))
            return ret
        else:
            # Integers, strings, None, etc.
            return value


    @property
    def transaction_pending(self):
        'Return True if we have pending transaction work that needs flushing out'
        return (len(self.clients) + len(self.newrels) + len(self.deletions)) > 0

    @staticmethod
    def callconstructor(constructor, kwargs):
        'Call a constructor (or function) in a (hopefully) correct way'
        try:
            args, _unusedvarargs, varkw, _unuseddefaults = inspect.getargspec(constructor)
        except TypeError:
            args, _unusedvarargs, varkw, _unuseddefaults = inspect.getargspec(constructor.__init__)
        newkwargs = {}
        extraattrs = {}
        if varkw: # Allows any keyword arguments
            newkwargs = kwargs
        else: # Only allows some keyword arguments
            for arg in kwargs:
                if arg in args:
                    newkwargs[arg] = kwargs[arg]
                else:
                    extraattrs[arg] = kwargs[arg]
        ret = constructor(**newkwargs)


        # Make sure the attributes match the desired values
        for attr in kwargs:
            kwa = kwargs[attr]
            if attr in extraattrs:
                if not hasattr(ret, attr) or getattr(ret, attr) != kwa:
                    object.__setattr__(ret, attr, kwa)
            elif not hasattr(ret, attr) or getattr(ret, attr) is None:
                # If the constructor set this attribute to a value, but it doesn't match the db
                # then we let it stay as the constructor set it
                # We gave this value to the constructor as a keyword argument.
                # Sometimes constructors need to do that...
                object.__setattr__(ret, attr, kwa)
        return ret

    def constructobj(self, constructor, node):
        'Create/construct an object from a Graph node'
        kwargs = node.get_properties()
        #print >> sys.stderr, 'constructobj NODE PROPERTIES', kwargs
        subj = Store.callconstructor(constructor, kwargs)
        #print >> sys.stderr, 'constructobj CONSTRUCTED NODE ', subj
        cls = subj.__class__
        (index_name, idxkey, idxvalue) = self._get_idx_key_value(cls,  {}, subj=subj)
        if not self.is_uniqueindex(index_name):
            raise ValueError("Class 'cls' must be a unique indexed class [%s]", cls)
        local = self._localsearch(cls, idxkey, idxvalue)
        if local is not None:
            return local
        else:
            self._register(subj, node=node)
            return subj

    @staticmethod
    def _safe_attr_names(subj):
        'Return the list of supported attribute names from the given object'
        ret = []
        for attr in subj.__dict__.keys():
            if attr[0] == '_':
                continue
            ret.append(attr)
        return ret

    @staticmethod
    def safe_attrs(subj):
        'Return a dictionary of supported attributes from the given object'
        ret = {}
        for attr in Store._safe_attr_names(subj):
            ret[attr] = subj.__dict__[attr]
        return ret

    @staticmethod
    def _proper_attr_value(obj, attr):
        'Ensure that the value being set is acceptable to neo4j.Node objects'
        value = getattr(obj, attr)
        if isinstance(value, (str, unicode, float, int, long, list, tuple)):
            return value
        else:
            print >> sys.stderr,  ("Attr %s of object %s of type %s isn't acceptable"
            %   (attr, obj, type(value)))
            raise ValueError("Attr %s of object %s of type %s isn't acceptable"
            %   (attr, obj, type(value)))

    @staticmethod
    def mark_dirty(objself, attr):
        'Mark the given attribute as dirty in our store'
        if hasattr(objself, '_Store__store_dirty_attrs'):
            objself.__store_dirty_attrs[attr] = True
            objself.__store.clients[objself] = True

    @staticmethod
    def _storesetattr(objself, name, value):
        '''
        Does a setattr() - and marks changed attributes "dirty".  This
        permits us to know when attributes change, and automatically
        include them in the next transaction.
        This is a GoodThing.
        '''

        if name[0] != '_':
            if hasattr(objself, '_Store__store_dirty_attrs'):
                try:
                    if getattr(objself, name) == value:
                        #print >> sys.stderr, 'Value of %s already set to %s' % (name, value)
                        return
                except AttributeError:
                    pass
                if objself.__store.readonly:
                    print >> sys.stderr, ('Caught %s being set to %s!' % (name, value))
                    raise RuntimeError('Attempt to set attribute %s using a read-only store' % name)
                if hasattr(value, '__iter__') and len(value) == 0:
                    raise ValueError(
                    'Attempt to set attribute %s to empty array (Neo4j limitation)' % name)

                objself.__store_dirty_attrs[name] = True
                objself.__store.clients[objself] = True
        object.__setattr__(objself, name, value)

    @staticmethod
    def _update_node_from_obj(subj):
        'Update the node from its paired object'
        node = subj.__store_node
        attrlist = subj.__store_dirty_attrs.keys()
        for attr in attrlist:
            node[attr] = Store._proper_attr_value(subj, attr)
            #print >> sys.stderr, ('SETTING node["%s"] to %s' %
            #                      (attr, Store._proper_attr_value(subj, attr)))
        subj.__store_dirty_attrs = {}

    def _update_obj_from_node(self, subj):
        'Update an object from its paired node - preserving "dirty" attributes'
        node = subj.__store_node
        nodeprops = node.get_properties()
        remove_subj = subj not in self.clients
        for attr in nodeprops.keys():
            pattr = nodeprops[attr]
            if attr in subj.__store_dirty_attrs:
                remove_subj = False
                continue
            #print >> sys.stderr, ('Setting obj["%s"] to %s' % (attr, pattr))
            # Avoid getting it marked as dirty...
            object.__setattr__(subj, attr, pattr)
        if remove_subj and subj in self.clients:
            del self.clients[subj]

        # Make sure everything in the object is in the Node...
        for attr in Store._safe_attr_names(subj):
            if attr not in nodeprops:
                subj.__store_dirty_attrs[attr] = True
                self.clients[subj] = True

    def reset_stats(self):
        'Reset all our statistical counters and timers'
        self.stats = {}
        for statname in ('nodecreate', 'relate', 'separate', 'index', 'attrupdate'
        ,       'index', 'nodedelete', 'addlabels'):
            self.stats[statname] = 0
        self.stats['lastcommit'] = None
        self.stats['totaltime'] = timedelta()

    def _bump_stat(self, statname, increment=1):
        'Increment the given statistic by the given increment - default increment is 1'
        self.stats[statname] += increment

    def _get_idx_key_value(self, cls, attrdict, subj=None):
        'Return the appropriate key/value pair for an object of a particular class'
        kmap = self.classkeymap[cls.__name__]
        #print ('GET_IDX_KEY_VALUE: attrdict', attrdict)
        #if subj is not None:
            #print ('GET_IDX_KEY_VALUE: subj.__dict___', subj.__dict__)
        if 'kattr' in kmap:
            kk = kmap['kattr']
            if hasattr(subj, kk):
                #print ('SUBJ.__dict__:%s, kk=%s' % (subj.__dict__, kk))
                key = getattr(subj, kk)
            else:
                #print ('ATTRDICT:%s, kk=%s' % (attrdict, kk))
                key = attrdict[kk]
        else:
            key = kmap['key']

        if 'vattr' in kmap:
            kv = kmap['vattr']
            if hasattr(subj, kv):
                value = getattr(subj, kv)
                #print ('KV SUBJ.__dict__:%s, kv=%s' % (subj.__dict__, kv))
            else:
                #print ('KV ATTRDICT:%s, kv=%s' % (attrdict, kv))
                value = attrdict[kv]
        else:
            value = kmap['value']
        return (self.classkeymap[cls.__name__]['index'], key, value)


    def _localsearch(self, cls, idxkey, idxvalue):
        '''Search the 'client' array and the weaknoderefs to see if we can find
        the requested object before going to the database'''

        classname = cls.__name__
        kmap = self.classkeymap[classname]
        searchlist = {}
        if 'kattr' in kmap:
            searchlist[kmap['kattr']] = idxkey
        if 'vattr' in kmap:
            searchlist[kmap['vattr']] = idxvalue


        searchset = self.clients.keys()
        for weakclient in self.weaknoderefs.values():
            client = weakclient()
            if client is not None and client not in self.clients:
                searchset.append(client)

        for client in searchset:
            if client.__class__ != cls:
                continue
            found = True
            for attr in searchlist.keys():
                if not hasattr(client, attr) or getattr(client, attr) != searchlist[attr]:
                    found = False
                    break
            if found:
                assert hasattr(client, '_Store__store_node')
                return client
        return None

    def _construct_obj_from_node(self, node, cls, clsargs=None):
        'Construct an object associated with the given node'
        clsargs = [] if clsargs is None else clsargs
        # Do we already have a copy of an object that goes with this node somewhere?
        # If so, we need to update and return it instead of creating a new object
        nodeid = node._id
        if nodeid in self.weaknoderefs:
            subj = self.weaknoderefs[nodeid]()
            if subj is None:
                del self.weaknoderefs[nodeid]
            else:
                # Yes, we have a copy laying around somewhere - update it...
                #print >> sys.stderr, ('WE HAVE NODE LAYING AROUND...', node.get_properties())
                self._update_obj_from_node(subj)
                return subj
        #print >> sys.stderr, 'NODE ID: %d, node = %s' % (node._id, str(node))
        retobj = Store.callconstructor(cls, node.get_properties())
        for attr in clsargs:
            if not hasattr(retobj, attr) or getattr(retobj, attr) is None:
                # None isn't a legal value for Neo4j to store in the database
                setattr(retobj, attr, clsargs[attr])
        return self._register(retobj, node=node)

    def _register(self, subj, node=None, index=None, unique=None, key=None, value=None):
        'Register this object with a Node, so we can track it for updates, etc.'

        if not isinstance(subj, object):
            raise(ValueError('Instances registered with Store class must be subclasses of object'))
        assert not hasattr(subj, '_Store__store')
        assert subj not in self.clients
        self.clients[subj] = True
        subj.__store = self
        subj.__store_node = node
        subj.__store_batchindex = None
        subj.__store_index = index
        subj.__store_index_key = key
        subj.__store_index_value = value
        subj.__store_index_unique = unique
        subj.__store_dirty_attrs = {}
        if subj.__class__ not in self.classes:
            subj.__class__.__setattr__ = Store._storesetattr
            self.classes[subj.__class__] = True
        if node is not None and node.bound:
            if node._id in self.weaknoderefs:
                weakling = self.weaknoderefs[node._id]()
                if weakling is None:
                    del self.weaknoderefs[node._id]
                else:
                    print >> sys.stderr, ('OOPS! - already here... self.weaknoderefs'
                    ,   weakling, weakling.__dict__)
            assert node._id not in self.weaknoderefs or self.weaknoderefs[node._id] is None
            self.weaknoderefs[node._id] = weakref.ref(subj)
        if node is not None:
            if 'post_db_init' in dir(subj):
                subj.post_db_init()
            if not node.bound:
                # Create an event to commemorate the creation of the new database object
                if AssimEvent.event_observation_enabled:
                    AssimEvent(subj, AssimEvent.CREATEOBJ)

        return subj

    def _new_nodes(self):
        'Return the set of newly created nodes for this transaction'
        ret = []
        for client in self.clients:
            if Store.is_abstract(client) and hasattr(client, '_Store__store_node'):
                node = client.__store_node
                ret.append((client, node))
        return ret


    @staticmethod
    def node(subj):
        'Returns the neo4j.Node associated with the given object'
        return subj.__store_node

    #
    #   Except for commit() and abort(), all member functions from here on
    #   construct the batch job from previous requests
    #

    def _batch_construct_create_nodes(self):
        'Construct batch commands for all the new objects in this batch'
        for pair in self._new_nodes():
            (subj, node) = pair
            Store._update_node_from_obj(subj)
            subj.__store_batchindex = self.batchindex
            if Store.debug:
                print >> sys.stderr, ('====== Performing batch.create(%d: %s) - for new node'
                %   (self.batchindex, str(node)))
            self.batchindex += 1
            self._bump_stat('nodecreate')
            self.batch.create(node)

    def _batch_construct_add_labels(self):
        'Construct batch commands for all the labels to be added for this batch'
        for pair in self._new_nodes():
            (subj, node) = pair
            self.batchindex += 1
            cls = subj.__class__
            if False and hasattr(cls, '__meta_labels__'):
                print >> sys.stderr, 'ADDING LABELS for', type(subj), cls.__meta_labels__()
                self._bump_stat('addlabels')
                self.batch.add_labels(node, cls.__meta_labels__())

    def _batch_construct_relate_nodes(self):
        'Construct the batch commands to create the requested relationships'
        for rel in self.newrels:
            fromobj = rel['from']
            toobj = rel['to']
            fromnode = fromobj.__store_node
            tonode = toobj.__store_node
            reltype = rel['type']
            props = rel['props']
            if not fromnode.bound:
                fromnode = fromobj.__store_batchindex
            if not tonode.bound:
                tonode = toobj.__store_batchindex
            if props is None:
                absrel = neo4j.Relationship(fromnode, reltype, tonode)
            else:
                absrel = neo4j.Relationship(fromnode, reltype, tonode, **props)
            # Record where this relationship will show up in batch output
            # No harm in remembering this until transaction end...
            rel['seqno'] = self.batchindex
            rel['abstract'] = absrel
            self.batchindex += 1
            if Store.debug:
                print >> sys.stderr, ('Performing batch.create(%s): node relationships'
                                      % absrel)
            self._bump_stat('relate')
            if Store.debug:
                print >> sys.stderr, ('ADDING rel %s' % absrel)
            self.batch.create(absrel)

    def _batch_construct_deletions(self):
        'Construct batch commands for removing relationships or nodes'
        delrels = {}
        delnodes = {}
        for relorobj in self.deletions:
            if isinstance(relorobj, neo4j.Relationship):
                relid = relorobj._id
                if relid not in delrels:
                    if Store.debug and Store.log:
                        Store.log.debug('DELETING rel %d: %s' % (relorobj._id, relorobj))
                    self._bump_stat('separate')
                    self.batch.delete(relorobj)
                    delrels[relid] = True
            else:
                # Then it must be a node-related object...
                if Store.debug and Store.log:
                    Store.log.debug('DELETING NODE %s: %s' %
                                    (str(relorobj.__dict__.keys()), relorobj))
                node = relorobj.__store_node
                nodeid = node._id
                if nodeid in delnodes:
                    continue
                if nodeid in self.weaknoderefs:
                    del self.weaknoderefs[nodeid]
                # disconnect it from the database
                for attr in relorobj.__dict__.keys():
                    if attr.startswith('_Store__store'):
                        delattr(relorobj, attr)
                if Store.debug and Store.log:
                    Store.log.debug('DELETING node %s' % node)
                self._bump_stat('nodedelete')
                self.batch.delete(node)
                delnodes[relid] = True


    def _batch_construct_new_index_entries(self):
        'Construct batch commands for adding newly created nodes to the indexes'
        for pair in self._new_nodes():
            subj = pair[0]
            if subj.__store_index is not None:
                idx, key, value = self._compute_batch_index(subj)
                if subj.__store_index_unique:
                    if Store.debug:
                        print >> sys.stderr,('add_to_index[_or_fail]: node %s; index %s("%s","%s")'
                            % (subj.__store_batchindex, idx, key, value))
                    vers = (  int(self.db.neo4j_version[0])*100
                            + int(self.db.neo4j_version[1])*10
                            + int(self.db.neo4j_version[2]))
                    if vers >= 210:
                        # Work around bug in add_to_index_or_fail()...
                        self.batch.add_to_index(neo4j.Node, idx, key, value
                        ,   subj.__store_batchindex)
                    else:
                        self.batch.add_to_index_or_fail(neo4j.Node, idx, key, value
                        ,   subj.__store_batchindex)

                else:
                    if Store.debug:
                        print >> sys.stderr, ('add_to_index: node %s added to index %s(%s,%s)' %
                            (subj.__store_batchindex, idx, key, value))
                    self.batch.add_to_index(neo4j.Node, idx, key, value
                    ,   subj.__store_batchindex)

    def _compute_batch_index(self, subj):
        '''
        Compute index information for a new node
        '''
        idx = self.db.legacy.get_index(neo4j.Node, subj.__store_index)
        key = subj.__store_index_key
        value = subj.__store_index_value
        self.index_entry_count += 1
        self._bump_stat('index')
        return (idx, key, value)

    def _batch_construct_node_updates(self):
        'Construct batch commands for updating attributes on "old" nodes'
        clientset = {}
        for subj in self.clients:
            assert subj not in clientset
            clientset[subj] = True
            node = subj.__store_node
            if not node.bound:
                continue
            for attr in subj.__store_dirty_attrs.keys():
                # Each of these items will return None in the HTTP stream...
                self.node_update_count += 1
                self._bump_stat('attrupdate')
                setattr(node, attr, Store._proper_attr_value(subj, attr))
                if Store.debug:
                    print >> sys.stderr, ('Setting property %s of node %d to %s' % (attr
                    ,       node._id, Store._proper_attr_value(subj, attr)))
                    if Store.log:
                        Store.log.debug('Setting property %s of %d to %s' % (attr
                        ,       node._id, Store._proper_attr_value(subj, attr)))
                self.batch.set_property(node, attr, Store._proper_attr_value(subj, attr))

    def abort(self):
        'Clear out any currently pending transaction work - start fresh'
        if self.batch is not None:
            self.batch = None
        self.batchindex = 0
        for subj in self.clients:
            subj.__store_dirty_attrs = {}
        self.clients = {}
        self.newrels = []
        self.deletions = []
        # Clean out dead node references
        for nodeid in self.weaknoderefs.keys():
            subj = self.weaknoderefs[nodeid]()
            if subj is None or not hasattr(subj, '_Store__store_node'):
                del self.weaknoderefs[nodeid]

    def commit(self):
        '''Commit all the changes we've created since our last transaction'''
        if Store.debug:
            print >> sys.stderr, ('COMMITTING THIS THING:', str(self))
        self.batch = self.batch if self.batch is not None \
                     else py2neo.legacy.LegacyWriteBatch(self.db)
        self.batchindex = 0
        self._batch_construct_create_nodes()        # These return new nodes in batch return result
        self._batch_construct_relate_nodes()        # These return new relationships
        self._batch_construct_new_index_entries()   # These return the objects indexed
        self._batch_construct_node_updates()        # These return None
        self._batch_construct_add_labels()          # Not sure what these return
        self._batch_construct_deletions()           # These return None
        if Store.debug:
            print >> sys.stderr, ('Batch Updates constructed: Committing THIS THING:', str(self))
            if Store.log:
                Store.log.debug('Batch Updates constructed: Committing THIS THING: %s'
                %   str(self))
        start = datetime.now()
        try:
            submit_results = self.batch.submit()
        except GraphError as e:
            print >> sys.stderr, ('FAILED TO COMMIT THIS THING:', str(self))
            print >> sys.stderr, self
            print >> sys.stderr, ('BatchError: %s' % e)
            raise e
        if Store.debug:
            print >> sys.stderr, 'SUBMIT RESULTS FOLLOW:'
            for result in submit_results:
                print >> sys.stderr, 'SUBMITRESULT:', type(result), result
        end = datetime.now()
        diff = end - start
        self.stats['lastcommit'] = diff
        self.stats['totaltime'] += diff

        # Save away (update) any newly created nodes...
        for pair in self._new_nodes():
            # unused variable
            # pylint: disable=W0612
            (subj, unused) = pair
            index = subj.__store_batchindex
            newnode = submit_results[index]
            if Store.debug:
                print >> sys.stderr, 'LOOKING at new node with batch index %d' % index
                print >> sys.stderr, 'NEW NODE looks like %s' % str(newnode)
                print >> sys.stderr, 'SUBJ (our copy) looks like %s' % str(subj)
                print >> sys.stderr, ('NEONODE (their copy) looks like %d, %s'
                %       (newnode._id, str(newnode.get_properties())))
            # This 'subj' used to have an abstract node, now it's concrete
            subj.__store_node = newnode
            self.weaknoderefs[newnode._id] = weakref.ref(subj)
            for attr in newnode.get_properties():
                if not hasattr(subj, attr):
                    print >> sys.stderr, ("OOPS - we're missing attribute %s" % attr)
                elif getattr(subj, attr) != newnode[attr]:
                    print >> sys.stderr, ("OOPS - attribute %s is %s and should be %s" \
                    %   (attr, getattr(subj, attr), newnode[attr]))
                    #self.dump_clients()
        self.abort()
        if Store.debug:
            print >> sys.stderr, 'DB TRANSACTION COMPLETED SUCCESSFULLY'
        return submit_results

    def clean_store(self):
        '''Clean out all the objects we used to have in our store - afterwards we
        have none associated with this Store'''
        for nodeid in self.weaknoderefs:
            obj = self.weaknoderefs[nodeid]()
            if obj is not None:
                for attr in obj.__dict__.keys():
                    if attr.startswith('_Store__store'):
                        delattr(obj, attr)
        self.weaknoderefs = {}
        self.abort()

if __name__ == "__main__":
    #pylint: disable=C0413
    from cmadb import Neo4jCreds
    # I'm not too concerned about this test code...
    # R0914:923,4:testme: Too many local variables (17/15)
    # pylint: disable=R0914
    def testme():
        'A little test code...'

        # Must be a subclass of 'object'...
        # pylint: disable=R0903
        class Drone(object):
            'This is a Class docstring'
            def __init__(self, a=None, b=None, name=None):
                'This is a doc string'
                self.a = a
                self.b = b
                self.name = name
            def foo_is_blacklisted(self):
                'This is a doc string too'
                return 'a=%s b=%s name=%s' % (self.a, self.b, self.name)

            @classmethod
            def __meta_labels__(cls):
                return ['Class_%s' % cls.__name__]

        Neo4jCreds().authenticate()
        ourdb = neo4j.Graph()
        ourdb.legacy.get_or_create_index(neo4j.Node, 'Drone')
        dbvers = ourdb.neo4j_version
        # Clean out the database
        if dbvers[0] >= 2:
            qstring = 'match (n) optional match (n)-[r]-() delete n,r'
        else:
            qstring = 'start n=node(*) match n-[r?]-() delete n,r'
        ourdb.cypher.run(qstring)
        # Which fields of which types are used for indexing
        classkeymap = {
            Drone:   # this is for the Drone class
                {'index':   'Drone',    # The index name for this class is 'Drone'
                'key':      'Drone',    # The key field is a constant - 'Drone'
                'vattr':    'name'      # The value field is an attribute - 'name'
                }
        }
        # uniqueindexmap and classkeymap are optional, but make save() much more convenient

        store = Store(ourdb, uniqueindexmap={'Drone': True}, classkeymap=classkeymap)
        DRONE = 'Drone121'

        # Construct an initial Drone
        #   fred = Drone(a=1,b=2,name=DRONE)
        #   store.save(fred)    # Drone is a 'known' type, so we know which fields are index key(s)
        #
        #   load_or_create() is the preferred way to create an object...
        #
        fred = store.load_or_create(Drone, a=1, b=2, name=DRONE)

        assert fred.a == 1
        assert fred.b == 2
        assert fred.name == DRONE
        assert not hasattr(fred, 'c')
        # Modify some fields -- add some...
        fred.a = 52
        fred.c = 3.14159
        assert fred.a == 52
        assert fred.b == 2
        assert fred.name == DRONE
        assert fred.c > 3.14158 and fred.c < 3.146
        # Create some relationships...
        rellist = ['ISA', 'WASA', 'WILLBEA']
        for rel in rellist:
            store.relate(fred, rel, fred)
        # These should have no effect - but let's make sure...
        for rel in rellist:
            store.relate_new(fred, rel, fred)
        store.commit()  # The updates have been captured...
        print >> sys.stderr, ('Statistics:', store.stats)

        assert fred.a == 52
        assert fred.b == 2
        assert fred.name == DRONE
        assert fred.c > 3.14158 and fred.c < 3.146

        #See if the relationships 'stuck'...
        for rel in rellist:
            ret = store.load_related(fred, rel, Drone)
            ret = [elem for elem in ret]
            assert len(ret) == 1 and ret[0] is fred
        for rel in rellist:
            ret = store.load_in_related(fred, rel, Drone)
            ret = [elem for elem in ret]
            assert len(ret) == 1 and ret[0] is fred
        assert fred.a == 52
        assert fred.b == 2
        assert fred.name == DRONE
        assert fred.c > 3.14158 and fred.c < 3.146
        print >> sys.stderr, (store)
        assert not store.transaction_pending

        #Add another new field
        fred.x = 'malcolm'
        store.dump_clients()
        print >> sys.stderr, ('store:', store)
        assert store.transaction_pending
        store.commit()
        print >> sys.stderr, ('Statistics:', store.stats)
        assert not store.transaction_pending
        assert fred.a == 52
        assert fred.b == 2
        assert fred.name == DRONE
        assert fred.c > 3.14158 and fred.c < 3.146
        assert fred.x == 'malcolm'

        # Check out load_indexed...
        newnode = store.load_indexed('Drone', 'Drone', fred.name, Drone)[0]
        print >> sys.stderr, ('LoadIndexed NewNode: %s %s' % (newnode, store.safe_attrs(newnode)))
        # It's dangerous to have two separate objects which are the same thing be distinct
        # so we if we fetch a node, and one we already have, we get the original one...
        assert fred is newnode
        if store.transaction_pending:
            print >> sys.stderr, ('UhOh, we have a transaction pending.')
            store.dump_clients()
            assert not store.transaction_pending
        assert newnode.a == 52
        assert newnode.b == 2
        assert newnode.x == 'malcolm'
        store.separate(fred, 'WILLBEA')
        assert store.transaction_pending
        store.commit()
        print >> sys.stderr, ('Statistics:', store.stats)

        # Test a simple cypher query...
        qstr = "START d=node:Drone('*:*') RETURN d"
        qnode = store.load_cypher_node(qstr, Drone) # Returns a single node
        print >> sys.stderr, ('qnode=%s' % qnode)
        assert qnode is fred
        qnodes = store.load_cypher_nodes(qstr, Drone) # Returns iterable
        qnodes = [qnode for qnode in qnodes]
        assert len(qnodes) == 1
        assert qnode is fred

        # See if the now-separated relationship went away...
        rels = store.load_related(fred, 'WILLBEA', Drone)
        rels = [rel for rel in rels]
        assert len(rels) == 0
        store.refresh(fred)
        store.delete(fred)
        assert store.transaction_pending
        store.commit()

        # When we delete an object from the database, the  python object
        # is disconnected from the database...
        assert not hasattr(fred, '_Store__store_node')
        assert not store.transaction_pending

        print >> sys.stderr, ('Statistics:', store.stats)
        print >> sys.stderr, ('Final returned values look good!')


    Store.debug = False
    testme()
