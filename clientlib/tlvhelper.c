/**
 * @file
 * @brief TLV helper functions.
 * The file provides a variety of getter and setter functions for TLV integers - all with error
 * checking.
 *
 * @author &copy; 2011 - Alan Robertson <alanr@unix.sh>
 * @n
 * Licensed under the GNU Lesser General Public License (LGPL) version 3 or any later version at your option,
 * excluding the provision allowing for relicensing under the GPL at your option.
 */

#include <string.h>
#include <glib.h>
#include <tlvhelper.h>
/// Retrieve an unsigned 8 bit integer from the given location with error checking.
guint8
tlv_get_guint8(const void * vitem,	///< Location to get int from
	       const void* bufend)	///< one byte past end of buffer
{
	const guint8* itemptr = (const guint8*)vitem;
	guint8 item;
	g_return_val_if_fail(vitem != NULL && vitem < bufend, (guint8)0xff);
	item = *itemptr;
	return item;
}
/// Set an unsigned 8 bit integer to the given location with error checking.
void
tlv_set_guint8(void *	vitem,	///< Location to stuff the int into
	       guint8	item,	///< Value to stuff into 'vitem'
	       const void*	bufend)	///< one byte past the end of this buffer
{
	guint8* itemptr = (guint8*)vitem;
	g_return_if_fail(vitem < bufend);
	*itemptr = item;
}

/// Retrieve an unsigned 16 bit integer from the given location with error checking and
/// without caring about byte alignment.
guint16
tlv_get_guint16(const void * vitem,	///< Location to get int from
		const void* bufend)	///< one byte past end of buffer
{
	const guint16* itemptr = (const guint16*)vitem;
	guint16 item;
	if (!(vitem != NULL && ((itemptr+1) <= (const guint16*)bufend))) {
		g_error("UhOh!");
	}
	g_return_val_if_fail(vitem != NULL && ((const void*)(itemptr+1) <= bufend), (guint16)0xffff);
	memcpy(&item, vitem, sizeof(item));
	return g_ntohs(item);
}
/// Set an unsigned 16 bit integer to the given location with error checking and
/// without caring about byte alignment.
void
tlv_set_guint16(void *	vitem,	///< Location to stuff the int into
		guint16	item,	///< Value to stuff into 'vitem'
		const void*	bufend)	///< one byte past the end of this buffer
{
	guint16* itemptr = (guint16*)vitem;
	g_return_if_fail(vitem != NULL && ((void*)(itemptr+1)) <= bufend);
	item =  g_htons(item);
	memcpy(vitem, &item, sizeof(item));
}

/// Retrieve an unsigned 32 bit integer from the given location with error checking and
/// without caring about byte alignment.
guint32
tlv_get_guint32(const void * vitem,	///< Location to get int from
		const void* bufend)	///< one byte past end of buffer
{
	const guint32* itemptr = (const guint32*)vitem;
	guint32 item;
	g_return_val_if_fail(vitem != NULL && ((const void*)(itemptr+1) <= bufend), (guint32)0xffffffff);
	memcpy(&item, vitem, sizeof(item));
	return g_ntohl(item);
}
/// Set an unsigned 32 bit integer to the given location with error checking and
/// without caring about byte alignment.
void
tlv_set_guint32(void *	vitem,	///< Location to stuff the int into
		guint32	item,	///< Value to stuff into 'vitem'
		const void*	bufend)	///< one byte past the end of this buffer
{
	guint32* itemptr = (guint32*)vitem;
	g_return_if_fail(vitem != NULL && ((void*)(itemptr+1) <= bufend));
	item =  g_htonl(item);
	memcpy(vitem, &item, sizeof(item));
}


/// Retrieve an unsigned 64 bit integer from the given location with error checking and
/// without caring about byte alignment.
guint64
tlv_get_guint64(const void * vitem,	///< Location to get int from
		const void* bufend)	///< one byte past end of buffer
{
	const guint64* itemptr = (const guint64*)vitem;
	guint64 item;
	g_return_val_if_fail(vitem != NULL && ((const void*)(itemptr+1) <= bufend), (guint32)0xffffffff);
	memcpy(&item, vitem, sizeof(item));
	return GINT64_FROM_BE(item);
}
/// Set an unsigned 64 bit integer to the given location with error checking and
/// without caring about byte alignment.
void
tlv_set_guint64(void *	vitem,	///< Location to stuff the int into
		guint64	item,	///< Value to stuff into 'vitem'
		const void*	bufend)	///< one byte past the end of this buffer
{
	guint64* itemptr = (guint64*)vitem;
	g_return_if_fail(vitem != NULL && ((void*)(itemptr+1) <= bufend));
	item =  GINT64_TO_BE(item);
	memcpy(vitem, &item, sizeof(item));
}
/// Retrieve an unsigned 24 bit (3-byte) integer from the given location with error checking and
/// without caring about byte alignment.  This is used for IEEE OUI values.
guint32
tlv_get_guint24(const void * vitem,	///< Location to get int from
		const void* bufend)	///< one byte past end of buffer
{
	guint32 item;
	guint8 firstbyte;
	g_return_val_if_fail(vitem != NULL && ((const void*)((const guint8*)vitem+3)) <= bufend, (guint32)0xffffff);
	firstbyte = *((const guint8*)vitem);
	///@todo verify that this 3-byte ordering is correct - it has to match the IEEE OUI layout...
	item = tlv_get_guint16((((const guint8 *)vitem+1)), bufend);
	item += ((((guint32)firstbyte)<<16)&0xff0000);
	return item;
}
/// Set an unsigned 24 bit (3-byte) integer to the given location with error checking and
/// without caring about byte alignment.  This is used for IEEE OUI values.
void
tlv_set_guint24(void *	vitem,	///< Location to stuff the int into
		guint32	item,	///< Value to stuff into 'vitem'
		const void*	bufend)	///< one byte past the end of this buffer
{
	guint8	firstbyte = ((item>>16)&0xff);
	guint16	item16;
	g_return_if_fail(vitem != NULL && (void*)(((guint8*)vitem)+3) <= bufend);
	item16 = (guint16) (item & 0xffff);
	///@todo verify that this 3-byte ordering is correct - it has to match the IEEE OUI layout...
	*((guint8 *)vitem) = firstbyte;
	tlv_set_guint16(((guint8 *)vitem+1), item16, bufend);
}
